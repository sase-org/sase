"""Clan hint-render structure, loading, and slow-tool tests."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.tui.models._agent_clan_sections import clan_section_member_rows
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    cache_clan_disk_snapshot,
    mark_clan_snapshot_loading,
    prepare_clan_section_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from tests.ace.tui.widgets._agent_display_clan_helpers import (
    make_clan_agent,
    rich_clan_snapshot,
)
from tests.ace.tui.widgets._agent_display_clan_hints_shared import (
    fold_app,
    warm_clan_snapshot,
)
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


def _roster_block(plain: str) -> list[str]:
    """Return the CLAN MEMBERS heading plus its contiguous roster rows."""
    lines = plain.splitlines()
    start = next(index for index, line in enumerate(lines) if "CLAN MEMBERS" in line)
    end = next(
        (index for index in range(start + 1, len(lines)) if not lines[index].strip()),
        len(lines),
    )
    return lines[start:end]


def test_clan_hint_render_preserves_folded_snapshot_structure(tmp_path: Path) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Summary at docs/summary.md"
    panel = FakePromptPanel()
    panel.app = fold_app(FoldLevel.EXPANDED)
    warm_clan_snapshot(panel, container, snapshot)

    expected = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.EXPANDED,
    ).plain
    panel.update_display_with_hints(container)
    actual = plain_of(panel.captured[-1])

    assert re.sub(r"\[\d+\] ", "", actual) == expected
    for heading in (
        "ERRORS",
        "OUTPUT VARIABLES",
        "WORKFLOW VARIABLES",
        "REPLIES",
        "SASE CONTEXT",
        "SLOW TOOL CALLS",
        "PROMPTS",
    ):
        assert heading in actual


def test_clan_member_jump_gutter_is_untouched_by_double_digit_hints(
    tmp_path: Path,
) -> None:
    """More than ten hints must not renumber or annotate the jump gutter."""
    members = [
        make_clan_agent(
            f"research.m{index}",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0) + timedelta(minutes=index),
            stop=datetime(2026, 7, 17, 12, 30, 0),
        )
        for index in range(12)
    ]
    for member in members:
        member.workspace_dir = str(tmp_path)
    container = project_clan_tree(members)[0]
    container.clan_summary = " ".join(f"docs/note{index}.md" for index in range(12))
    state = HeaderHintState(1, {}, None, {})

    plain_render = build_clan_detail_text(
        container,
        fold_level=FoldLevel.FULLY_EXPANDED,
    ).plain
    hinted = build_clan_detail_text(
        container,
        fold_level=FoldLevel.FULLY_EXPANDED,
        hint_state=state,
    ).plain

    assert len(state.hint_mappings) == 12
    assert "[12] docs/note11.md" in hinted
    hinted_roster = _roster_block(hinted)
    assert hinted_roster == _roster_block(plain_render)
    assert not [line for line in hinted_roster if re.search(r"\[\d+\]", line)]


def test_clan_slow_tool_hints_register_report_specs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    container, snapshot = rich_clan_snapshot()
    disk = snapshot.disk
    assert disk is not None
    slow_tool = disk.slow_tool_calls[0]
    entry = replace(
        slow_tool.call.entry,
        status="success",
        tool_use_id="clan-success",
        source_path="/tmp/tool-calls.jsonl",
        line_number=17,
    )
    call = replace(slow_tool.call, entry=entry)
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            slow_tool_calls=(replace(slow_tool, call=call),),
        ),
    )
    panel = FakePromptPanel()
    panel.app = fold_app(FoldLevel.EXPANDED)
    warm_clan_snapshot(panel, container, snapshot)

    result = panel.update_display_with_hints(container)
    plain = plain_of(panel.captured[-1])

    report_hints = {
        number: path
        for number, path in result.file_hints.items()
        if path in result.tool_call_reports
    }
    assert len(report_hints) == 1
    report_hint, report_path = next(iter(report_hints.items()))
    assert f"• .one · [{report_hint}] Bash · 2m 5s · just check" in plain
    assert report_path.startswith(str(tmp_path / ".sase" / "tool_call_reports"))
    spec = result.tool_call_reports[report_path]
    assert spec.entry is entry
    assert spec.agent_name == ".one"
    assert spec.source_label == "attempt 1"


def test_clan_hint_render_reports_loading_and_enriched_states() -> None:
    container, snapshot = rich_clan_snapshot()
    container.clan_summary = "No paths in this summary"

    loading_panel = FakePromptPanel()
    prepare_clan_section_snapshot(loading_panel, container)
    mark_clan_snapshot_loading(loading_panel, container, {"replies"})
    loading = loading_panel.update_display_with_hints(container)

    enriched_panel = FakePromptPanel()
    warm_clan_snapshot(enriched_panel, container, snapshot)
    enriched = enriched_panel.update_display_with_hints(container)

    assert loading.header_enrichment_pending
    assert not enriched.header_enrichment_pending


def test_clan_snapshot_merge_invalidates_cached_hint_document() -> None:
    container, snapshot = rich_clan_snapshot()
    panel = FakePromptPanel()
    warm_clan_snapshot(panel, container, snapshot)
    panel.update_display_with_hints(container)

    assert panel.hint_document_is_current(container)
    disk = snapshot.disk
    assert disk is not None
    merged = cache_clan_disk_snapshot(panel, container, disk)

    assert merged is not None and merged.revision == 2
    assert not panel.hint_document_is_current(container)

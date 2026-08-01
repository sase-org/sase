"""Clan detail-panel file-hint tests."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from sase.ace.tui.models._agent_clan_sections import (
    ClanSectionSnapshot,
    clan_section_member_rows,
)
from sase.ace.tui.models.agent import Agent
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
from tests.ace.tui.widgets._agent_display_clan_helpers import rich_clan_snapshot
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


def _fold_app(level: FoldLevel) -> SimpleNamespace:
    return SimpleNamespace(
        panel_fold_level=level,
        _panel_fold_overrides=SimpleNamespace(snapshot=lambda: {}),
    )


def _warm_clan_snapshot(
    panel: FakePromptPanel,
    container: Agent,
    snapshot: ClanSectionSnapshot,
) -> None:
    prepare_clan_section_snapshot(panel, container)
    disk = snapshot.disk
    assert disk is not None
    assert cache_clan_disk_snapshot(panel, container, disk) is not None


def test_clan_summary_paths_render_ordered_hints_from_member_workspace(
    tmp_path: Path,
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "[bold]Review src/first.py, then @docs/second.md.[/bold]"
    panel = FakePromptPanel()
    panel.app = _fold_app(FoldLevel.COLLAPSED)
    _warm_clan_snapshot(panel, container, snapshot)

    result = panel.update_display_with_hints(container)
    plain = plain_of(panel.captured[-1])

    assert result.file_hints == {
        1: str(tmp_path / "src/first.py"),
        2: str(tmp_path / "docs/second.md"),
    }
    assert "Review [1] src/first.py, then [2] @docs/second.md." in plain
    assert "AGENT PROMPT" not in plain
    assert "No prompt file found." not in plain
    assert not result.header_enrichment_pending


def test_clan_hint_render_preserves_folded_snapshot_structure(tmp_path: Path) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Summary at docs/summary.md"
    panel = FakePromptPanel()
    panel.app = _fold_app(FoldLevel.EXPANDED)
    _warm_clan_snapshot(panel, container, snapshot)

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


def test_clan_summary_styles_survive_hint_insertion(tmp_path: Path) -> None:
    container, _snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "[bold #FFD75F]See src/styled.py[/bold #FFD75F]"
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(container, hint_state=state)
    bold_span = next(
        span for span in rendered.spans if str(span.style) == "bold #ffd75f"
    )

    assert rendered.plain[bold_span.start : bold_span.end] == ("See [1] src/styled.py")
    assert state.hint_mappings == {1: str(tmp_path / "src/styled.py")}


def test_clan_hint_render_reports_loading_and_enriched_states() -> None:
    container, snapshot = rich_clan_snapshot()
    container.clan_summary = "No paths in this summary"

    loading_panel = FakePromptPanel()
    prepare_clan_section_snapshot(loading_panel, container)
    mark_clan_snapshot_loading(loading_panel, container, {"replies"})
    loading = loading_panel.update_display_with_hints(container)

    enriched_panel = FakePromptPanel()
    _warm_clan_snapshot(enriched_panel, container, snapshot)
    enriched = enriched_panel.update_display_with_hints(container)

    assert loading.header_enrichment_pending
    assert not enriched.header_enrichment_pending


def test_clan_snapshot_merge_invalidates_cached_hint_document() -> None:
    container, snapshot = rich_clan_snapshot()
    panel = FakePromptPanel()
    _warm_clan_snapshot(panel, container, snapshot)
    panel.update_display_with_hints(container)

    assert panel.hint_document_is_current(container)
    disk = snapshot.disk
    assert disk is not None
    merged = cache_clan_disk_snapshot(panel, container, disk)

    assert merged is not None and merged.revision == 2
    assert not panel.hint_document_is_current(container)

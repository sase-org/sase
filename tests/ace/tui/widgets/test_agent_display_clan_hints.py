"""Clan detail-panel file-hint tests."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanDiskSnapshot,
    ClanSectionSnapshot,
    ClanTextEntry,
    aggregate_clan_in_memory,
    clan_section_member_rows,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
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
from sase.ace.tui.widgets.prompt_panel._hint_caps import HINT_TRUNCATION_MESSAGE
from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_LINES
from tests.ace.tui.widgets._agent_display_clan_helpers import (
    make_clan_agent,
    rich_clan_snapshot,
)
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


def _snapshot_with_text(
    container: Agent,
    *,
    replies: tuple[ClanTextEntry, ...] = (),
    prompts: tuple[ClanTextEntry, ...] = (),
) -> ClanSectionSnapshot:
    disk = ClanDiskSnapshot(
        loaded_sections=CLAN_DISK_SECTIONS,
        members=(),
        replies=replies,
        prompts=prompts,
        context_lanes=(),
        slow_tool_calls=(),
    )
    return ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(container),
        disk=disk,
    )


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


def test_clan_summary_skips_paths_inside_http_urls(tmp_path: Path) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    url = "https://github.com/sase-org/sase--beads/blob/main/pages/sase-d9/README.md"
    container.clan_summary = f"Read {url}, then open docs/local.md."
    panel = FakePromptPanel()
    panel.app = _fold_app(FoldLevel.COLLAPSED)
    _warm_clan_snapshot(panel, container, snapshot)

    result = panel.update_display_with_hints(container)
    plain = plain_of(panel.captured[-1])

    assert result.file_hints == {1: str(tmp_path / "docs/local.md")}
    assert f"Read {url}, then open [1] docs/local.md." in plain


def test_clan_summary_prefers_worker_resolved_plan_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Plan: plans:202608/clan.md"
    resolved = str(tmp_path / "plan-store" / "202608" / "clan.md")
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            hint_paths={"202608/clan.md": resolved},
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_reference",
        Mock(side_effect=AssertionError("renderer performed a plan-store lookup")),
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        snapshot=snapshot,
        hint_state=state,
    )

    assert "Plan: [1] plans:202608/clan.md" in rendered.plain
    assert state.hint_mappings == {1: resolved}
    start = rendered.plain.index("plans:202608/clan.md")
    end = start + len("plans:202608/clan.md")
    assert any(
        str(span.style).casefold() == "#87afff"
        and span.start <= start
        and span.end >= end
        for span in rendered.spans
    )


def test_clan_summary_unindexed_prompt_is_not_hijacked_by_plan_suffix(
    tmp_path: Path,
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Path: plans:202608/x.md\nPrompt: prompts/202608/x.md"
    plan_target = str(tmp_path / "sase" / "repos" / "plans" / "202608" / "x.md")
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            hint_paths={
                "plans:202608/x.md": plan_target,
                "202608/x.md": plan_target,
                plan_target: plan_target,
            },
        ),
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        snapshot=snapshot,
        hint_state=state,
    )

    assert "Path: [1] plans:202608/x.md" in rendered.plain
    assert "Prompt: [2] prompts/202608/x.md" in rendered.plain
    assert state.hint_mappings == {
        1: plan_target,
        2: str(tmp_path / "prompts" / "202608" / "x.md"),
    }


def test_clan_summary_prompt_row_resolves_to_archived_prompt_index(
    tmp_path: Path,
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Path: plans:202608/x.md\nPrompt: prompts/202608/x.md"
    plan_target = str(tmp_path / "sase" / "repos" / "plans" / "202608" / "x.md")
    prompt_target = str(
        tmp_path
        / ".sase"
        / "projects"
        / "demo"
        / "repos"
        / "agents"
        / "prompts"
        / "202608"
        / "x.md"
    )
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            hint_paths={
                "plans:202608/x.md": plan_target,
                "202608/x.md": plan_target,
                plan_target: plan_target,
                "prompts/202608/x.md": prompt_target,
            },
        ),
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        snapshot=snapshot,
        hint_state=state,
    )

    assert "Path: [1] plans:202608/x.md" in rendered.plain
    assert "Prompt: [2] prompts/202608/x.md" in rendered.plain
    assert state.hint_mappings == {1: plan_target, 2: prompt_target}


def test_clan_summary_matches_known_artifact_suffix(tmp_path: Path) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Artifact: reports/findings.md"
    resolved = str(tmp_path / "artifacts" / "reports" / "findings.md")
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            hint_paths={
                str(tmp_path / "artifacts" / "reports" / "findings.md"): resolved
            },
        ),
    )
    state = HeaderHintState(1, {}, None, {})

    build_clan_detail_text(container, snapshot=snapshot, hint_state=state)

    assert state.hint_mappings == {1: resolved}


def test_clan_summary_unresolved_token_uses_workspace_fallback(tmp_path: Path) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Unknown: docs/missing.md"
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        snapshot=snapshot,
        hint_state=state,
    )

    assert "Unknown: [1] docs/missing.md" in rendered.plain
    assert state.hint_mappings == {1: str(tmp_path / "docs" / "missing.md")}


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


def _roster_block(plain: str) -> list[str]:
    """Return the CLAN MEMBERS heading plus its contiguous roster rows."""
    lines = plain.splitlines()
    start = next(index for index, line in enumerate(lines) if "CLAN MEMBERS" in line)
    end = next(
        (index for index in range(start + 1, len(lines)) if not lines[index].strip()),
        len(lines),
    )
    return lines[start:end]


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
    panel.app = _fold_app(FoldLevel.EXPANDED)
    _warm_clan_snapshot(panel, container, snapshot)

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


def test_clan_level_two_hints_only_rendered_triage_entries(tmp_path: Path) -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.workspace_dir = str(tmp_path)
    container = project_clan_tree([member])[0]
    replies = tuple(
        ClanTextEntry(
            member_identity=member.identity,
            member_label=".one",
            kind="AGENT REPLY",
            preview=f"src/preview-{index}.py",
            body=f"src/full-{index}.py",
        )
        for index in range(10)
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=replies),
        fold_level=FoldLevel.EXPANDED,
    )

    assert len(state.hint_mappings) == 8
    assert list(state.hint_mappings.values()) == [
        str(tmp_path / f"src/preview-{index}.py") for index in range(8)
    ]
    assert "[8] src/preview-7.py" in rendered.plain
    assert "preview-8.py" not in rendered.plain
    assert "+2 more" in rendered.plain
    assert "full-0.py" not in rendered.plain


def test_clan_full_bodies_use_each_members_workspace(tmp_path: Path) -> None:
    started = datetime(2026, 7, 17, 12, 0, 0)
    first = make_clan_agent("research.one", status="RUNNING", start=started)
    second = make_clan_agent(
        "research.two",
        status="RUNNING",
        start=started + timedelta(seconds=1),
    )
    first_workspace = tmp_path / "one"
    second_workspace = tmp_path / "two"
    first_workspace.mkdir()
    second_workspace.mkdir()
    first.workspace_dir = str(first_workspace)
    second.workspace_dir = str(second_workspace)
    container = project_clan_tree([first, second])[0]
    replies = tuple(
        ClanTextEntry(
            member_identity=member.identity,
            member_label=label,
            kind="AGENT REPLY",
            preview="src/shared.py",
            body="Open src/shared.py",
        )
        for member, label in ((first, ".one"), (second, ".two"))
    )
    state = HeaderHintState(1, {}, None, {})

    build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=replies),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert state.hint_mappings == {
        1: str(first_workspace / "src/shared.py"),
        2: str(second_workspace / "src/shared.py"),
    }


def test_clan_member_workspace_is_resolved_lazily_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = make_clan_agent(
        "research.one",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.error_message = "logs/error.txt"
    container = project_clan_tree([member])[0]
    replies = (
        ClanTextEntry(
            member_identity=member.identity,
            member_label=".one",
            kind="AGENT REPLY",
            preview="src/first.py",
            body="src/first.py and src/second.py",
        ),
    )
    resolve_workspace = Mock(return_value="/workspace")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_clan."
        "resolve_agent_workspace_dir",
        resolve_workspace,
    )
    state = HeaderHintState(1, {}, None, {})

    build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=replies),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    resolve_workspace.assert_called_once()


def test_clan_full_sections_hint_values_and_bodies_but_not_variable_names(
    tmp_path: Path,
) -> None:
    member = make_clan_agent(
        "research.one",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.workspace_dir = str(tmp_path)
    member.error_message = "Failure details in logs/error.txt"
    member.error_traceback = 'File "src/crash.py", line 4'
    member.output_variables = {"src/name.py": "data/value.json"}
    member.step_output = {"meta_note": "reports/workflow.md"}
    container = project_clan_tree([member])[0]
    reply = ClanTextEntry(
        member_identity=member.identity,
        member_label=".one",
        kind="AGENT REPLY",
        preview="src/reply.py",
        body="Reply body src/reply.py",
    )
    prompt = ClanTextEntry(
        member_identity=member.identity,
        member_label=".one",
        kind="AGENT PROMPT",
        preview="src/prompt.py",
        body="Prompt body src/prompt.py",
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(
            container,
            replies=(reply,),
            prompts=(prompt,),
        ),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert list(state.hint_mappings.values()) == [
        str(tmp_path / "logs/error.txt"),
        str(tmp_path / "src/crash.py"),
        str(tmp_path / "data/value.json"),
        str(tmp_path / "reports/workflow.md"),
        str(tmp_path / "src/reply.py"),
        str(tmp_path / "src/prompt.py"),
    ]
    assert re.search(r"\[\d+\] src/name\.py", rendered.plain) is None


def test_clan_member_bodies_share_one_hint_budget(tmp_path: Path) -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.workspace_dir = str(tmp_path)
    container = project_clan_tree([member])[0]
    body = "\n".join(
        (
            "src/head.py",
            *(f"filler {index}" for index in range(PLAIN_RENDER_MAX_LINES)),
            "src/tail.py",
        )
    )
    reply = ClanTextEntry(
        member_identity=member.identity,
        member_label=".one",
        kind="AGENT REPLY",
        preview="src/head.py",
        body=body,
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        hint_state=state,
        snapshot=_snapshot_with_text(container, replies=(reply,)),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert HINT_TRUNCATION_MESSAGE in rendered.plain
    assert state.hint_mappings == {1: str(tmp_path / "src/head.py")}
    assert "src/tail.py" not in rendered.plain

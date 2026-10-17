"""Clan summary and plan-token file-hint tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.ace.tui.models._agent_clan_sections import (
    ClanContextEntry,
    ClanContextLane,
    clan_section_member_rows,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from tests.ace.tui.widgets._agent_display_clan_helpers import rich_clan_snapshot
from tests.ace.tui.widgets._agent_display_clan_hints_shared import (
    fold_app,
    warm_clan_snapshot,
)
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


def test_clan_summary_paths_render_ordered_hints_from_member_workspace(
    tmp_path: Path,
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "[bold]Review src/first.py, then @docs/second.md.[/bold]"
    panel = FakePromptPanel()
    panel.app = fold_app(FoldLevel.COLLAPSED)
    warm_clan_snapshot(panel, container, snapshot)

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
    panel.app = fold_app(FoldLevel.COLLAPSED)
    warm_clan_snapshot(panel, container, snapshot)

    result = panel.update_display_with_hints(container)
    plain = plain_of(panel.captured[-1])

    assert result.file_hints == {1: str(tmp_path / "docs/local.md")}
    assert f"Read {url}, then open [1] docs/local.md." in plain


def test_clan_summary_prefers_worker_resolved_plan_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker's full logical token alias is authoritative for rendering."""
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Plan: plan:202608/clan.md"
    resolved = str(tmp_path / "plan-store" / "202608" / "clan.md")
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            hint_paths={"plan:202608/clan.md": resolved},
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

    assert "Plan: [1] plan:202608/clan.md" in rendered.plain
    assert state.hint_mappings == {1: resolved}
    start = rendered.plain.index("plan:202608/clan.md")
    end = start + len("plan:202608/clan.md")
    assert any(
        str(span.style).casefold() == "#87afff"
        and span.start <= start
        and span.end >= end
        for span in rendered.spans
    )


@pytest.mark.parametrize(
    "hint_paths",
    [
        {},
        {"202608/x.md": "/wrong/suffix.md"},
        {"prompts/202608/x.md": "/wrong/prompt.md"},
    ],
)
def test_unindexed_logical_plan_hint_keeps_its_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hint_paths: dict[str, str],
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Path: plan:202608/x.md"
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(snapshot, disk=replace(disk, hint_paths=hint_paths))
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_reference",
        Mock(side_effect=AssertionError("renderer performed a plan-store lookup")),
    )
    state = HeaderHintState(1, {}, None, {})

    build_clan_detail_text(container, snapshot=snapshot, hint_state=state)

    assert state.hint_mappings == {1: "plan:202608/x.md"}


def test_fold_level_three_plan_context_hint_keeps_logical_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, snapshot = rich_clan_snapshot()
    disk = snapshot.disk
    assert disk is not None
    lane = ClanContextLane(
        label="PLAN",
        entries=(
            ClanContextEntry(
                key="plan:X/Y.md",
                label="plan:X/Y.md",
                member_labels=(".one",),
                values=("plan:X/Y.md",),
            ),
        ),
    )
    snapshot = replace(snapshot, disk=replace(disk, context_lanes=(lane,)))
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_reference",
        Mock(side_effect=AssertionError("renderer performed a plan-store lookup")),
    )
    state = HeaderHintState(1, {}, None, {})

    rendered = build_clan_detail_text(
        container,
        snapshot=snapshot,
        hint_state=state,
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert "SASE CONTEXT" in rendered.plain
    assert "plan:X/Y.md" in state.hint_mappings.values()


def test_clan_summary_unindexed_prompt_is_not_hijacked_by_plan_suffix(
    tmp_path: Path,
) -> None:
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Path: plan:202608/x.md\nPrompt: prompts/202608/x.md"
    plan_target = str(tmp_path / "sase" / "repos" / "plans" / "202608" / "x.md")
    disk = snapshot.disk
    assert disk is not None
    snapshot = replace(
        snapshot,
        disk=replace(
            disk,
            hint_paths={
                "plan:202608/x.md": plan_target,
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

    assert "Path: [1] plan:202608/x.md" in rendered.plain
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
    container.clan_summary = "Path: plan:202608/x.md\nPrompt: prompts/202608/x.md"
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
                "plan:202608/x.md": plan_target,
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

    assert "Path: [1] plan:202608/x.md" in rendered.plain
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

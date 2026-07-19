"""Fold-aware family-container detail panel tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_family import (
    FAMILY_PROMPT_SECTION_ID,
    FAMILY_REPLY_SECTION_ID,
    FAMILY_XPROMPT_SECTION_ID,
    _family_roster_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


def _family(
    tmp_path: Path,
    *,
    in_clan: bool = False,
) -> tuple[Agent, Agent]:
    started = datetime(2026, 7, 18, 12, 0, 0)
    root_dir = tmp_path / ("clan-plan" if in_clan else "standalone-plan")
    child_dir = tmp_path / ("clan-code" if in_clan else "standalone-code")
    root_dir.mkdir()
    child_dir.mkdir()
    _write_phase_content(root_dir, "plan")
    _write_phase_content(child_dir, "code")

    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-test",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started,
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260718120000",
        artifacts_dir=str(root_dir),
        response_path=str(root_dir / "response.md"),
        agent_name="alpha--plan",
        agent_family="alpha",
        agent_family_role="plan",
        role_suffix="--plan",
        plan_chain_root=True,
        model="claude/opus",
        agent_clan="map" if in_clan else None,
        output_variables={"plan_path": "/tmp/plan.md"},
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-test",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started + timedelta(minutes=2),
        stop_time=started + timedelta(minutes=5),
        raw_suffix="20260718120200",
        artifacts_dir=str(child_dir),
        response_path=str(child_dir / "response.md"),
        agent_name="alpha--code",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--code",
        model="claude/sonnet",
        agent_clan="map" if in_clan else None,
        output_variables={"code_path": "/tmp/code.md"},
    )
    root.followup_agents = [child]
    assert root.is_family_container_row is True
    return root, child


def _write_phase_content(directory: Path, role: str) -> None:
    (directory / "raw_xprompt.md").write_text(
        "\n".join(f"{role} xprompt line {index}" for index in range(1, 16)) + "\n",
        encoding="utf-8",
    )
    (directory / "01_prompt.md").write_text(
        "\n".join(f"{role} prompt line {index}" for index in range(1, 16)) + "\n",
        encoding="utf-8",
    )
    (directory / "response.md").write_text(
        "\n".join(f"{role} reply line {index}" for index in range(1, 7)) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("in_clan", [False, True])
def test_family_roster_numbers_real_chain_rows_in_order(
    tmp_path: Path,
    in_clan: bool,
) -> None:
    root, child = _family(tmp_path, in_clan=in_clan)

    entries = _family_roster_entries(root, now=root.stop_time)
    published = []
    header, _ = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    )

    assert [entry.identity for entry in entries] == [root.identity, child.identity]
    assert [entry.label for entry in entries] == ["--plan", "--code"]
    assert [entry.kind for entry in entries] == ["PLANNER", "CODER"]
    assert "Fold: 1/2\n" in header.plain
    assert "▾ ❖ FAMILY MEMBERS · 2\n" in header.plain
    assert header.plain.index("FAMILY MEMBERS") < header.plain.index("OUTPUT VARIABLES")
    assert [target.member_identity for target in published[0].targets] == [
        root.identity,
        child.identity,
    ]


def test_loaded_plan_family_roster_uses_concrete_member_state_and_content(
    tmp_path: Path,
) -> None:
    started = datetime(2026, 7, 19, 9, 0, 0)
    root_dir = tmp_path / "aggregate-root"
    planner_dir = tmp_path / "concrete-planner"
    coder_dir = tmp_path / "concrete-coder"
    for directory, role in (
        (root_dir, "aggregate"),
        (planner_dir, "planner"),
        (coder_dir, "coder"),
    ):
        directory.mkdir()
        _write_phase_content(directory, role)

    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="ep",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started,
        run_start_time=started,
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260719090000",
        artifacts_dir=str(root_dir),
        response_path=str(root_dir / "response.md"),
        workflow="ace-run",
        agent_name="ep--plan",
        agent_family="ep",
        agent_family_role="root",
        role_suffix="--plan",
        plan_chain_root=True,
        plan_action="tale",
        model="aggregate/model",
        llm_provider="aggregate",
    )
    root.plan_times = [started + timedelta(minutes=2)]
    planner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="ep-planner-step",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started,
        run_start_time=started,
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260719090000-plan-step",
        parent_timestamp=root.raw_suffix,
        parent_workflow="ace-run",
        step_type="agent",
        artifacts_dir=str(planner_dir),
        response_path=str(planner_dir / "response.md"),
        agent_name="ep--plan-step",
        agent_family="ep",
        agent_family_role="plan",
        role_suffix="--plan",
        model="claude/opus",
        llm_provider="claude",
        workspace_num=21,
        activity="drafted the concrete plan",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="ep-coder",
        project_file="/tmp/family.sase",
        status="RUNNING",
        start_time=started + timedelta(minutes=3),
        run_start_time=started + timedelta(minutes=3),
        raw_suffix="20260719090300",
        parent_timestamp=root.raw_suffix,
        artifacts_dir=str(coder_dir),
        response_path=str(coder_dir / "response.md"),
        agent_name="ep--code",
        agent_family="ep",
        agent_family_role="code",
        role_suffix="--code",
        model="codex/gpt-5",
        llm_provider="codex",
        workspace_num=22,
        activity="implementing the approved tale",
    )

    _apply_status_overrides([root, coder], [planner])
    ordered = sort_and_reorder([root, coder], [planner])
    now = started + timedelta(minutes=5)
    entries = _family_roster_entries(root, now=now)
    published = []
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.FULLY_EXPANDED,
        member_jump_map_publisher=published.append,
    )

    assert ordered[:3] == [root, planner, coder]
    assert root.status == "WORKING TALE"
    assert root.runtime_children == [planner, coder]
    assert [entry.identity for entry in entries] == [
        planner.identity,
        coder.identity,
    ]
    assert [entry.presented_name for entry in entries] == [
        "ep--plan-step",
        "ep--code",
    ]
    assert [entry.status for entry in entries] == [
        "TALE APPROVED",
        "WORKING TALE",
    ]
    assert [entry.effective_bucket for entry in entries] == ["Done", "Running"]
    assert [entry.model for entry in entries] == [
        "claude/opus",
        "codex/gpt-5",
    ]
    assert [entry.duration for entry in entries] == ["2m", "2m"]
    assert entries[0].digest is not None
    assert entries[0].digest.activity == "drafted the concrete plan"
    assert entries[0].digest.workspace_num == 21
    assert entries[1].digest is not None
    assert entries[1].digest.activity == "implementing the approved tale"
    assert entries[1].digest.workspace_num == 22
    assert [target.member_identity for target in published[0].targets] == [
        planner.identity,
        coder.identity,
    ]
    assert "drafted the concrete plan" in header.plain
    assert "implementing the approved tale" in header.plain
    assert "ws 21" in header.plain
    assert "ws 22" in header.plain
    assert "✓ TALE APPROVED" in header.plain
    assert "▶ WORKING TALE" in header.plain

    panel = FakePromptPanel()
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.FULLY_EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])
    assert "planner reply line 1" in plain
    assert "coder reply line 1" in plain
    assert "aggregate reply line 1" not in plain


def test_shared_collapsed_level_maps_family_to_bounded_previews(
    tmp_path: Path,
) -> None:
    root, _child = _family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "plan xprompt line 15" not in plain
    assert "▾ AGENT PROMPT\n" in plain
    assert "plan prompt line 12" in plain
    assert "plan prompt line 15" not in plain
    assert "▾ AGENT REPLY · 2\n" in plain
    assert "plan reply line 1" not in plain
    assert "plan reply line 6" in plain


def test_expanded_family_sections_render_bounded_previews(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.EXPANDED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "… +3 more lines" in plain
    assert "plan xprompt line 15" not in plain
    assert "plan prompt line 12" in plain
    assert "plan prompt line 15" not in plain
    assert "plan reply line 1" not in plain
    assert "plan reply line 6" in plain
    assert "… +2 earlier lines" in plain


def test_exhaustive_shared_level_clamps_to_full_family_view(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)
    full_panel = FakePromptPanel()
    full_header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.FULLY_EXPANDED,
    )
    full_panel._update_family_display(
        root,
        full_header,
        error,
        panel_level=FoldLevel.FULLY_EXPANDED,
        section_fold_overrides={},
    )
    exhaustive_panel = FakePromptPanel()
    exhaustive_header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.EXHAUSTIVE,
    )
    exhaustive_panel._update_family_display(
        root,
        exhaustive_header,
        error,
        panel_level=FoldLevel.EXHAUSTIVE,
        section_fold_overrides={},
    )

    assert plain_of(exhaustive_panel.captured[-1]) == plain_of(full_panel.captured[-1])


def test_fully_expanded_family_sections_preserve_full_content(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.FULLY_EXPANDED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.FULLY_EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▼ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 15" in plain
    assert "plan prompt line 15" in plain
    assert "plan reply line 1" in plain
    assert "code reply line 1" in plain


def test_family_omits_empty_xprompt_and_prompt_sections(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)
    artifacts_dir = Path(root.artifacts_dir or "")
    (artifacts_dir / "raw_xprompt.md").unlink()
    (artifacts_dir / "01_prompt.md").unlink()
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "AGENT XPROMPT" not in plain
    assert "No xprompt file found." not in plain
    assert "AGENT PROMPT" not in plain
    assert "No prompt file found." not in plain
    assert "▾ AGENT REPLY · 2\n" in plain


def test_family_keeps_pending_reply_state(tmp_path: Path) -> None:
    root, child = _family(tmp_path)
    Path(root.response_path or "").unlink()
    Path(child.response_path or "").unlink()
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT REPLY · 2\n" in plain
    assert plain.count("No response content yet.") == 2


def test_family_section_override_wins_over_collapsed_panel(
    tmp_path: Path,
) -> None:
    root, _child = _family(tmp_path)

    overrides = {FAMILY_PROMPT_SECTION_ID: FoldLevel.FULLY_EXPANDED}
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
        family_section_fold_overrides=overrides,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides=overrides,
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "plan xprompt line 15" not in plain
    assert "▼ AGENT PROMPT\n" in plain
    assert "plan prompt line 15" in plain
    assert "▾ AGENT REPLY · 2\n" in plain


def test_family_header_maps_shared_shallow_levels_to_preview(tmp_path: Path) -> None:
    root, _child = _family(tmp_path)

    collapsed, _ = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.COLLAPSED,
    )
    expanded, _ = build_header_text(
        root,
        cheap=True,
        family_fold_level=FoldLevel.EXPANDED,
    )

    assert "Fold: 1/2\n" in collapsed.plain
    assert "▾ OUTPUT VARIABLES · 2\n" in collapsed.plain
    assert "plan_path: /tmp/plan.md" in collapsed.plain
    assert "▾ OUTPUT VARIABLES · 2\n" in expanded.plain
    assert "plan_path: /tmp/plan.md" in expanded.plain
    assert "code_path: /tmp/code.md" in expanded.plain


def test_family_section_ids_remain_stable() -> None:
    assert FAMILY_XPROMPT_SECTION_ID == "agent-xprompt"
    assert FAMILY_PROMPT_SECTION_ID == "agent-prompt"
    assert FAMILY_REPLY_SECTION_ID == "agent-reply"

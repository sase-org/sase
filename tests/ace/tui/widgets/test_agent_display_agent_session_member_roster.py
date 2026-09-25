"""Tests for the SESSION SHELLS roster on family-member detail panels."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
    agent_session_roster_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    make_agent_session,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_kind_header


def test_member_panel_lists_only_sibling_and_publishes_jump_map(
    tmp_path: Path,
) -> None:
    root, child = make_agent_session(tmp_path)

    published = []
    header, _ = build_header_text(
        child,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=published.append,
    )

    assert_kind_header(header, "AGENT SHELL", "#FFD700")
    assert header.plain.startswith("AGENT SHELL\nName:")
    assert "FAMILY\n" not in header.plain.split("SESSION SHELLS", 1)[0]
    assert "▾ ❖ SESSION SHELLS · 1 · alpha" in header.plain
    entries = agent_session_roster_entries(root, exclude=child)
    assert [entry.label for entry in entries] == ["--plan"]
    assert [entry.identity for entry in entries] == [root.identity]

    assert len(published) == 1
    jump_map = published[0]
    assert jump_map.container_identity == child.identity
    assert [target.member_identity for target in jump_map.targets] == [root.identity]
    assert all(target.member_identity != child.identity for target in jump_map.targets)


def test_plan_workflow_agent_session_member_panels_list_each_other() -> None:
    started = datetime(2026, 7, 19, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="ep",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started,
        run_start_time=started,
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260719090000",
        workflow="ace-run",
        agent_name="ep--plan",
        agent_session="ep",
        agent_session_role="root",
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
        agent_name="ep--plan-step",
        agent_session="ep",
        agent_session_role="plan",
        role_suffix="--plan",
        model="claude/opus",
        llm_provider="claude",
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
        agent_name="ep--code",
        agent_session="ep",
        agent_session_role="code",
        role_suffix="--code",
        model="codex/gpt-5",
        llm_provider="codex",
    )

    _apply_status_overrides([root, coder], [planner])
    sort_and_reorder([root, coder], [planner])

    planner_published = []
    planner_header, _ = build_header_text(
        planner,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=planner_published.append,
    )
    coder_published = []
    coder_header, _ = build_header_text(
        coder,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=coder_published.append,
    )

    assert "SESSION SHELLS" in planner_header.plain
    assert "--code" in planner_header.plain
    assert [target.member_identity for target in planner_published[0].targets] == [
        coder.identity
    ]

    assert "SESSION SHELLS" in coder_header.plain
    assert "--plan" in coder_header.plain
    assert [target.member_identity for target in coder_published[0].targets] == [
        planner.identity
    ]


def test_three_member_agent_session_middle_member_lists_others_in_chain_order() -> None:
    started = datetime(2026, 8, 1, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="tri",
        project_file="/tmp/tri.sase",
        status="DONE",
        start_time=started,
        stop_time=started + timedelta(minutes=1),
        raw_suffix="20260801090000",
        agent_name="tu.f0--0",
        agent_session="tu.f0",
        agent_session_role="plan",
        role_suffix="--0",
        plan_chain_root=True,
        model="claude/opus",
    )
    member1 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="tri",
        project_file="/tmp/tri.sase",
        status="DONE",
        start_time=started + timedelta(minutes=1),
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260801090100",
        parent_timestamp=root.raw_suffix,
        agent_name="tu.f0--1",
        agent_session="tu.f0",
        agent_session_role="code",
        role_suffix="--1",
        model="claude/sonnet",
    )
    member2 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="tri",
        project_file="/tmp/tri.sase",
        status="RUNNING",
        start_time=started + timedelta(minutes=2),
        raw_suffix="20260801090200",
        parent_timestamp=root.raw_suffix,
        agent_name="tu.f0--code",
        agent_session="tu.f0",
        agent_session_role="code",
        role_suffix="--code",
        model="claude/sonnet",
    )
    root.followup_agents = [member1, member2]
    # Production sets this in ``sort_and_reorder`` (``_attach_agent_session_containers``).
    member1.agent_session_container = root
    member2.agent_session_container = root
    assert root.is_agent_session_container_row is True

    entries = agent_session_roster_entries(root, exclude=member1)
    assert [entry.identity for entry in entries] == [root.identity, member2.identity]

    published = []
    header, _ = build_header_text(
        member1,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=published.append,
    )

    assert "SESSION SHELLS" in header.plain
    jump_map = published[0]
    assert jump_map.container_identity == member1.identity
    assert [target.number for target in jump_map.targets] == ["0", "1"]
    assert [target.member_identity for target in jump_map.targets] == [
        root.identity,
        member2.identity,
    ]


def test_agent_session_roster_labels_monitor_members() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="DONE",
        start_time=started,
        stop_time=started + timedelta(minutes=1),
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        status_bucket="Running",
        start_time=started + timedelta(minutes=1),
        run_start_time=started + timedelta(minutes=1),
        raw_suffix="20260812090100",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon",
        agent_session="alpha",
        agent_session_role="monitor",
        role_suffix="--mon",
        model="shell",
        monitor_id="m123",
        monitor_state="running",
        monitor_label="just check",
        monitor_command="just check-full",
    )
    root.followup_agents = [monitor]

    entries = agent_session_roster_entries(root)

    assert [
        (entry.label, entry.kind, entry.status, entry.model, entry.effective_bucket)
        for entry in entries
    ] == [
        ("--0", "AGENT (0)", "DONE", "default", "Done"),
        ("--mon", "⚙ MONITOR", "MONITORING", "just check", "Running"),
    ]
    header, _ = build_header_text(root, cheap=True, lane_fold_level=FoldLevel.EXPANDED)
    assert "SESSION SHELLS · 2\n" in header.plain
    assert "⚙ MONITOR" in header.plain
    assert "just check" in header.plain
    assert "shell" not in header.plain.split("⚙ MONITOR", 1)[1].split("\n", 1)[0]


def test_agent_session_roster_inserts_nested_monitor_after_starter_and_excludes_self() -> (
    None
):
    started = datetime(2026, 8, 12, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="DONE",
        start_time=started,
        stop_time=started + timedelta(minutes=1),
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
        model="claude/opus",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="DONE",
        start_time=started + timedelta(minutes=1),
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260812090100",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--code",
        agent_session="alpha",
        agent_session_role="code",
        role_suffix="--code",
        model="codex/gpt-5",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="MONITORED",
        start_time=started + timedelta(minutes=2),
        stop_time=started + timedelta(minutes=3),
        raw_suffix="20260812090200",
        parent_timestamp=coder.raw_suffix,
        agent_name="alpha--mon",
        agent_session="alpha",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="m123",
        monitor_state="completed",
        monitor_command="just check-full --every-target\nand a second line",
    )
    review = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started + timedelta(minutes=3),
        raw_suffix="20260812090300",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--review",
        agent_session="alpha",
        agent_session_role="review",
        role_suffix="--review",
        model="claude/sonnet",
    )
    root.followup_agents = [coder, review]
    root.runtime_children = [coder, review]
    coder.followup_agents = [monitor]
    coder.runtime_children = [monitor]
    coder.agent_session_container = root
    monitor.agent_session_container = root
    review.agent_session_container = root

    entries = agent_session_roster_entries(root)
    assert [entry.label for entry in entries] == [
        "--0",
        "--code",
        "--mon",
        "--review",
    ]
    assert entries[2].kind == "⚙ MONITOR"
    assert entries[2].model == "just check-full --every-target"
    assert entries[2].effective_bucket == "Done"

    sibling_entries = agent_session_roster_entries(root, exclude=monitor)
    assert [entry.label for entry in sibling_entries] == ["--0", "--code", "--review"]

    published = []
    header, _ = build_header_text(
        monitor,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=published.append,
    )
    assert "▾ ❖ SESSION SHELLS · 3 · alpha" in header.plain
    assert [target.member_identity for target in published[0].targets] == [
        root.identity,
        coder.identity,
        review.identity,
    ]


def test_agent_session_roster_monitor_descriptor_falls_back_to_command() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="DONE",
        start_time=started,
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
    )
    unlabeled = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-family",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started + timedelta(minutes=1),
        raw_suffix="20260812090100",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon",
        agent_session="alpha",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="m-unlabeled",
        monitor_state="running",
    )
    root.followup_agents = [unlabeled]

    assert agent_session_roster_entries(root)[1].model == "command"
    unlabeled.monitor_command = "  pytest -q  "
    assert agent_session_roster_entries(root)[1].model == "pytest -q"


def test_member_panel_stays_on_agent_scale_across_fold_levels(
    tmp_path: Path,
) -> None:
    root, child = make_agent_session(tmp_path)
    root.activity = "drafting the approach"
    root.workspace_num = 7

    collapsed, _ = build_header_text(
        child,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
    )
    expanded, _ = build_header_text(
        child,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
    )
    fully_expanded, _ = build_header_text(
        child,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
    )

    for header in (collapsed, expanded, fully_expanded):
        assert "Fold:" not in header.plain

    assert "drafting the approach" not in collapsed.plain
    assert "drafting the approach" in expanded.plain
    assert "ws 7" not in expanded.plain
    assert "drafting the approach" in fully_expanded.plain
    assert "ws 7" in fully_expanded.plain


def test_row_without_agent_session_container_renders_no_roster() -> None:
    lone = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="lone",
        project_file="/tmp/lone.sase",
        status="RUNNING",
        start_time=datetime(2026, 8, 1, 9, 0, 0),
        raw_suffix="20260801090000",
    )
    assert lone.agent_session_container is None

    header, _ = build_header_text(lone, cheap=True)

    assert "SESSION SHELLS" not in header.plain


def test_container_panel_output_is_unchanged_by_member_roster_support(
    tmp_path: Path,
) -> None:
    root, child = make_agent_session(tmp_path)

    published = []
    header, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    )

    assert "Fold: 1/2\n" in header.plain
    assert "▾ ❖ SESSION SHELLS · 2\n" in header.plain
    assert [target.member_identity for target in published[0].targets] == [
        root.identity,
        child.identity,
    ]

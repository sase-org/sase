"""Concrete sequential family-member projection tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_family_members import (
    MonitorLaneCounts,
    _concrete_agent_rows,
    concrete_agent_statuses,
    concrete_family_member_rows,
    family_member_status_buckets,
    is_sequential_family_container,
    monitor_lane_counts,
    panel_monitor_lane_counts,
)

_STARTED = datetime(2026, 7, 19, 9, 0, 0)


def _agent(
    name: str,
    *,
    role: str,
    parent_timestamp: str | None = None,
    workflow_child: bool = False,
    start_offset: int = 0,
    stop_offset: int | None = None,
    status: str = "DONE",
    status_bucket: str | None = None,
    step_type: str = "agent",
) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/family.sase",
        status=status,
        start_time=_STARTED + timedelta(minutes=start_offset),
        status_bucket=status_bucket,
        stop_time=(
            _STARTED + timedelta(minutes=stop_offset)
            if stop_offset is not None
            else None
        ),
        raw_suffix=f"suffix-{name}",
        parent_timestamp=parent_timestamp,
        agent_name=name,
        agent_family="alpha",
        agent_family_role=role,
        role_suffix=f"--{role}",
    )
    if workflow_child:
        agent.parent_workflow = "ace-run"
        agent.step_type = step_type
    return agent


def _plan_root(*, name: str = "alpha--plan") -> Agent:
    root = _agent(name, role="root")
    root.plan_chain_root = True
    root.role_suffix = "--plan"
    return root


def test_concrete_planner_replaces_aggregate_root_and_mixed_links_dedupe() -> None:
    root = _plan_root()
    planner = _agent(
        "alpha--plan-step",
        role="plan",
        parent_timestamp=root.raw_suffix,
        workflow_child=True,
    )
    feedback = _agent(
        "alpha--2",
        role="feedback",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    synthetic = _agent(
        "alpha--synthetic-plan",
        role="plan",
        parent_timestamp=root.raw_suffix,
    )
    synthetic.is_synthetic_planner = True
    parallel = _agent(
        "alpha--parallel",
        role="review",
        parent_timestamp=root.raw_suffix,
    )
    parallel.agent_family_parallel = True

    root.runtime_children = [planner, feedback, coder, synthetic, parallel]
    root.followup_agents = [synthetic, feedback, coder, parallel]

    assert concrete_family_member_rows(root) == (planner, feedback, coder)


def test_rename_on_attach_root_remains_the_first_real_member() -> None:
    root = _agent("alpha--0", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert concrete_family_member_rows(root) == (root, coder)


def test_promoted_plan_family_root_no_longer_double_counted_as_member() -> None:
    """A derived plan-family root's main step, not the root, is member #0.

    Mirrors the 'pv' bug family: a root promoted to '--0' (plan_chain_root
    stays False) whose plan chain only started later in a member. Once
    ``derived_plan_family_root`` is set, the root must stop standing in as
    member #0 or the lane header's "N agents · M awaiting" count double-counts
    it alongside the mirrored status.
    """
    root = _agent("pv", role="root")
    root.role_suffix = "--0"
    root.derived_plan_family_root = True
    main_step = _agent(
        "pv--0",
        role="q",
        parent_timestamp=root.raw_suffix,
        workflow_child=True,
        status="ANSWERED",
        stop_offset=1,
    )
    plan_member = _agent(
        "pv--1",
        role="plan",
        parent_timestamp=root.raw_suffix,
        status="TALE",
        start_offset=2,
    )
    root.runtime_children = [main_step, plan_member]
    root.followup_agents = [plan_member]

    statuses = concrete_agent_statuses(root)

    assert [entry.agent for entry in statuses] == [main_step, plan_member]
    assert [entry.bucket for entry in statuses] == ["Done", "Stopped"]


def test_plan_root_without_concrete_planner_uses_root_fallback() -> None:
    root = _plan_root(name="alpha")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    synthetic = _agent(
        "alpha--synthetic-plan",
        role="plan",
        parent_timestamp=root.raw_suffix,
    )
    synthetic.is_synthetic_planner = True
    root.runtime_children = [synthetic, coder]
    root.followup_agents = [synthetic, coder]

    assert concrete_family_member_rows(root) == (root, coder)


def test_bare_non_plan_container_stays_execution_neutral() -> None:
    root = _agent("alpha", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
    )
    root.followup_agents = [coder]

    assert concrete_family_member_rows(root) == (coder,)


def test_workflow_aggregate_projects_only_loaded_agent_steps() -> None:
    root = _agent("workflow", role="root")
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    main = _agent(
        "workflow-main",
        role="main",
        workflow_child=True,
    )
    python_step = _agent(
        "workflow-python",
        role="python",
        workflow_child=True,
        step_type="python",
    )
    root.runtime_children = [main, python_step]

    assert _concrete_agent_rows(root) == (main,)
    assert _concrete_agent_rows(python_step) == ()


def test_workflow_without_loaded_agent_steps_falls_back_to_root() -> None:
    root = _agent("workflow", role="root")
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    python_step = _agent(
        "workflow-python",
        role="python",
        workflow_child=True,
        step_type="python",
    )
    root.runtime_children = [python_step]

    assert _concrete_agent_rows(root) == (root,)


def test_approved_non_final_family_member_projects_done() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="TALE APPROVED",
    )
    coder = _agent(
        "alpha--code",
        role="code",
        status="WORKING TALE",
    )

    assert family_member_status_buckets((planner, coder)) == ("Done", "Running")


def test_approved_final_family_member_keeps_global_running_bucket() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="PLAN APPROVED",
    )

    assert family_member_status_buckets((planner,)) == ("Running",)


def test_custom_final_family_member_bucket_override_wins() -> None:
    monitor = _agent(
        "alpha--mon",
        role="monitor",
        status="MONITORED",
        status_bucket="Done",
    )

    assert family_member_status_buckets((monitor,)) == ("Done",)
    assert concrete_agent_statuses(monitor) == ()


def test_monitor_family_member_rows_do_not_count_as_agents() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _agent(
        "alpha--mon",
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="MONITORING",
        status_bucket="Running",
    )
    monitor.monitor_id = "m123"
    monitor.monitor_state = "running"
    root.followup_agents = [monitor]

    assert concrete_family_member_rows(root) == (root, monitor)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_monitor_starter_root_still_counts_as_concrete_agent() -> None:
    root = _agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    root.role_suffix = "--0"
    root.monitor_id = "m123"
    monitor = _agent(
        "alpha--mon",
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="MONITORED",
        status_bucket="Done",
    )
    monitor.monitor_id = "m123"
    monitor.monitor_state = "completed"
    root.followup_agents = [monitor]

    assert root.is_monitor is False
    assert concrete_family_member_rows(root) == (root, monitor)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_stopped_non_final_family_member_projects_done() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="ANSWERED",
        stop_offset=1,
    )
    coder = _agent(
        "alpha--1",
        role="code",
        status="DONE",
    )

    assert family_member_status_buckets((planner, coder)) == ("Done", "Done")


def test_unknown_status_on_stopped_non_final_member_projects_done() -> None:
    predecessor = _agent(
        "alpha--0",
        role="root",
        status="SOME NEW STATUS",
        stop_offset=1,
    )
    successor = _agent(
        "alpha--1",
        role="code",
        status="DONE",
    )

    assert family_member_status_buckets((predecessor, successor)) == (
        "Done",
        "Done",
    )


def test_running_non_final_family_member_keeps_running_bucket() -> None:
    predecessor = _agent(
        "alpha--0",
        role="root",
        status="RUNNING",
    )
    successor = _agent(
        "alpha--reviewer",
        role="review",
        status="WAITING",
    )

    assert family_member_status_buckets((predecessor, successor)) == (
        "Running",
        "Waiting",
    )


def _monitor_member(
    name: str,
    *,
    root: Agent,
    monitor_id: str,
    monitor_state: str | None,
    stop_offset: int | None = None,
) -> Agent:
    monitor = _agent(
        name,
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="MONITORING" if monitor_state == "running" else "MONITORED",
        status_bucket="Running" if monitor_state == "running" else "Done",
        stop_offset=stop_offset,
    )
    monitor.monitor_id = monitor_id
    monitor.monitor_state = monitor_state
    return monitor


def test_monitor_lane_counts_partitions_running_and_every_terminal_state() -> None:
    root = _agent("alpha--0", role="root")
    running = _monitor_member(
        "alpha--mon-running", root=root, monitor_id="m1", monitor_state="running"
    )
    monitors = [running] + [
        _monitor_member(
            f"alpha--mon-{state}",
            root=root,
            monitor_id=state,
            monitor_state=state,
            stop_offset=5,
        )
        for state in ("completed", "stopped", "failed", "timeout", "lost")
    ]
    root.followup_agents = monitors

    lanes = monitor_lane_counts(root)

    assert lanes == MonitorLaneCounts(running=1, settled=5)
    assert lanes.running + lanes.settled == len(monitors)


def test_monitor_lane_counts_unknown_state_without_stop_time_counts_running() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state=None
    )
    root.followup_agents = [monitor]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=1, settled=0)


def test_monitor_lane_counts_unknown_state_with_stop_time_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m1",
        monitor_state=None,
        stop_offset=5,
    )
    root.followup_agents = [monitor]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=0, settled=1)


def test_monitor_lane_counts_running_state_with_stop_time_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m1",
        monitor_state="running",
        stop_offset=5,
    )
    root.followup_agents = [monitor]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=0, settled=1)


def test_monitor_lane_counts_aggregates_clan_members_at_depth_two() -> None:
    clan = _agent("workers", role="root")
    clan.is_clan_container = True

    family_a = _agent("alpha--0", role="root")
    monitor_a = _monitor_member(
        "alpha--mon", root=family_a, monitor_id="ma", monitor_state="running"
    )
    family_a.followup_agents = [monitor_a]

    family_b = _agent("beta--0", role="root")
    monitor_b = _monitor_member(
        "beta--mon",
        root=family_b,
        monitor_id="mb",
        monitor_state="completed",
        stop_offset=5,
    )
    family_b.followup_agents = [monitor_b]

    clan.runtime_children = [family_a, family_b]

    assert monitor_lane_counts(clan) == MonitorLaneCounts(running=1, settled=1)


def test_monitor_lane_counts_dedupes_overlap_and_terminates_on_cycles() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    # Real family rows attach the same member to both lists.
    root.runtime_children = [monitor]
    root.followup_agents = [monitor]
    # A cycle back to the root: without a cycle guard this would recurse
    # forever.
    monitor.runtime_children = [root]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=1, settled=0)


def test_monitor_lane_counts_returns_zero_for_plain_agent() -> None:
    agent = _agent("alpha--code", role="code")

    assert monitor_lane_counts(agent) == MonitorLaneCounts()


def test_monitor_only_child_does_not_make_starter_a_family_container() -> None:
    starter = _agent("alpha--2", role="code")
    monitor = _agent(
        "alpha--mon-1",
        role="monitor",
        parent_timestamp=starter.raw_suffix,
        status="MONITORING",
        status_bucket="Running",
    )
    monitor.monitor_id = "m1"
    monitor.monitor_state = "running"
    starter.runtime_children = [monitor]
    starter.followup_agents = [monitor]

    assert is_sequential_family_container(starter) is False


def test_member_plus_monitor_still_makes_a_family_container() -> None:
    starter = _agent("alpha--2", role="code")
    continuation = _agent(
        "alpha--3",
        role="code",
        parent_timestamp=starter.raw_suffix,
        start_offset=1,
    )
    monitor = _agent(
        "alpha--mon-1",
        role="monitor",
        parent_timestamp=starter.raw_suffix,
        status="MONITORING",
        status_bucket="Running",
        start_offset=2,
    )
    monitor.monitor_id = "m1"
    monitor.monitor_state = "running"
    starter.runtime_children = [continuation, monitor]
    starter.followup_agents = [continuation, monitor]

    assert is_sequential_family_container(starter) is True


def test_failed_and_question_non_final_members_keep_their_buckets() -> None:
    successor = _agent(
        "alpha--1",
        role="code",
        status="DONE",
    )
    failed = _agent(
        "alpha--failed",
        role="root",
        status="FAILED",
        stop_offset=1,
    )
    question = _agent(
        "alpha--question",
        role="root",
        status="QUESTION",
    )

    assert family_member_status_buckets((failed, successor)) == (
        "Failed",
        "Done",
    )
    assert family_member_status_buckets((question, successor)) == (
        "Stopped",
        "Done",
    )


def test_panel_monitor_lane_counts_partitions_across_top_level_rows() -> None:
    root_a = _agent("alpha--0", role="root")
    root_a.followup_agents = [
        _monitor_member(
            "alpha--mon-running", root=root_a, monitor_id="ma", monitor_state="running"
        )
    ]
    root_b = _agent("beta--0", role="root")
    root_b.followup_agents = [
        _monitor_member(
            "beta--mon-done",
            root=root_b,
            monitor_id="mb",
            monitor_state="completed",
            stop_offset=5,
        )
    ]

    assert panel_monitor_lane_counts([root_a, root_b]) == MonitorLaneCounts(
        running=1, settled=1
    )


def test_panel_monitor_lane_counts_dedupes_monitor_reachable_from_two_roots() -> None:
    shared_root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=shared_root, monitor_id="m1", monitor_state="running"
    )
    root_a = _agent("alpha--0", role="root")
    root_a.runtime_children = [monitor]
    root_b = _agent("alpha--1", role="root")
    root_b.followup_agents = [monitor]

    assert panel_monitor_lane_counts([root_a, root_b]) == MonitorLaneCounts(
        running=1, settled=0
    )


def test_panel_monitor_lane_counts_counts_a_top_level_monitor_row() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m1",
        monitor_state="completed",
        stop_offset=5,
    )

    assert panel_monitor_lane_counts([monitor]) == MonitorLaneCounts(
        running=0, settled=1
    )


def test_panel_monitor_lane_counts_reaches_monitor_nested_two_levels_down() -> None:
    clan = _agent("workers", role="root")
    clan.is_clan_container = True
    family = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=family,
        monitor_id="m1",
        monitor_state="completed",
        stop_offset=5,
    )
    family.followup_agents = [monitor]
    clan.runtime_children = [family]

    assert panel_monitor_lane_counts([clan]) == MonitorLaneCounts(running=0, settled=1)


def test_panel_monitor_lane_counts_stop_time_without_state_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    settled = _monitor_member(
        "alpha--mon-settled",
        root=root,
        monitor_id="m1",
        monitor_state=None,
        stop_offset=5,
    )
    running = _monitor_member(
        "alpha--mon-running", root=root, monitor_id="m2", monitor_state=None
    )
    root.followup_agents = [settled, running]

    assert panel_monitor_lane_counts([root]) == MonitorLaneCounts(running=1, settled=1)


def test_panel_monitor_lane_counts_empty_and_monitor_free_input() -> None:
    assert panel_monitor_lane_counts([]) == MonitorLaneCounts()

    plain = _agent("alpha--code", role="code")
    assert panel_monitor_lane_counts([plain]) == MonitorLaneCounts()


def test_panel_monitor_lane_counts_terminates_on_a_cycle() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    root.runtime_children = [monitor]
    monitor.runtime_children = [root]

    assert panel_monitor_lane_counts([root]) == MonitorLaneCounts(running=1, settled=0)

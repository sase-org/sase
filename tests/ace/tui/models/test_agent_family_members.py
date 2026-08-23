"""Concrete sequential family-member projection tests."""

from __future__ import annotations

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_family_members import (
    _concrete_agent_rows,
    concrete_agent_statuses,
    concrete_family_member_rows,
    concrete_family_shell_rows,
    current_family_shell_row,
    is_sequential_family_container,
)
from sase.ace.tui.models.agent_loader import _apply_status_overrides

from ._agent_family_members_helpers import (
    _agent,
    _monitor_member,
    _plan_root,
    _plan_root_with_main_step,
)


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

    assert concrete_family_shell_rows(root) == (root, monitor)
    assert concrete_family_member_rows(root) == (root,)
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
    assert concrete_family_shell_rows(root) == (root, monitor)
    assert concrete_family_member_rows(root) == (root,)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_root_monitor_follows_its_planner_step_anchor() -> None:
    root, main_step = _plan_root_with_main_step()
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="running",
    )
    root.runtime_children = [main_step, monitor]
    root.followup_agents = [monitor]

    assert concrete_family_shell_rows(root) == (main_step, monitor)


def test_root_monitor_precedes_later_continuations() -> None:
    root, main_step = _plan_root_with_main_step()
    root_monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="completed",
        stop_offset=5,
    )
    continuation = _agent(
        "alpha--1",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    continuation_monitor = _monitor_member(
        "alpha--mon-0",
        root=continuation,
        monitor_id="m-cont",
        monitor_state="running",
    )
    root.runtime_children = [main_step, continuation, root_monitor]
    root.followup_agents = [continuation, root_monitor]
    continuation.runtime_children = [continuation_monitor]
    continuation.followup_agents = [continuation_monitor]

    assert concrete_family_shell_rows(root) == (
        main_step,
        root_monitor,
        continuation,
        continuation_monitor,
    )


def test_planner_step_projection_keeps_every_monitor() -> None:
    root, main_step = _plan_root_with_main_step()
    root_monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="completed",
        stop_offset=5,
    )
    continuation = _agent(
        "alpha--1",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    continuation_monitor = _monitor_member(
        "alpha--mon-0",
        root=continuation,
        monitor_id="m-cont",
        monitor_state="running",
    )
    root.runtime_children = [main_step, continuation, root_monitor]
    root.followup_agents = [continuation, root_monitor]
    continuation.runtime_children = [continuation_monitor]
    continuation.followup_agents = [continuation_monitor]

    loaded = {
        main_step.identity,
        root_monitor.identity,
        continuation.identity,
        continuation_monitor.identity,
    }
    assert {row.identity for row in concrete_family_shell_rows(root)} == loaded


def test_root_monitor_follows_root_when_no_step_is_loaded() -> None:
    root = _plan_root()
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="running",
    )
    root.followup_agents = [monitor]

    assert concrete_family_shell_rows(root) == (root, monitor)


def test_nested_monitor_follows_mid_family_continuation() -> None:
    root = _agent("alpha--0", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = _monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-nested",
        monitor_state="running",
    )
    review = _agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    root.runtime_children = [coder, review]
    root.followup_agents = [coder, review]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]

    assert concrete_family_shell_rows(root) == (root, coder, monitor, review)
    assert concrete_family_member_rows(root) == (root, coder, review)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [
        root,
        coder,
        review,
    ]


def test_shell_projection_dedupes_overlapping_links_and_identity() -> None:
    root = _agent("alpha--0", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = _monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-overlap",
        monitor_state="running",
    )
    alias = _monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-overlap",
        monitor_state="running",
    )
    alias.raw_suffix = monitor.raw_suffix
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [alias]

    assert concrete_family_shell_rows(root) == (root, coder, monitor)
    assert concrete_family_member_rows(root) == (root, coder)


def test_shell_projection_terminates_on_cycles() -> None:
    root = _agent("alpha--0", role="root")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = _monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-cycle",
        monitor_state="running",
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    monitor.runtime_children = [root]

    assert concrete_family_shell_rows(root) == (root, coder, monitor)


def test_attach_family_containers_reaches_nested_monitor_without_rerooting() -> None:
    root = _agent("alpha--0", role="root")
    root.plan_chain_root = True
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = _monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-attach",
        monitor_state="completed",
        stop_offset=5,
    )

    _apply_status_overrides([root, coder, monitor])
    ordered = sort_and_reorder([root, coder, monitor], [])

    assert root in ordered
    assert coder.family_container is root
    assert monitor.family_container is root
    assert monitor in coder.runtime_children
    assert monitor not in root.runtime_children


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


def test_current_family_shell_selects_active_promoted_root() -> None:
    root = _agent("alpha--0", role="root", status="RUNNING")
    waiting_child = _agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="WAITING",
        start_offset=1,
    )
    root.followup_agents = [waiting_child]

    assert current_family_shell_row(root) is root


def test_current_family_shell_selects_later_serial_continuation() -> None:
    root = _agent("alpha--0", role="root", status="DONE", stop_offset=1)
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="RUNNING",
        start_offset=2,
    )
    queued = _agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="QUEUED",
        start_offset=3,
    )
    root.runtime_children = [coder, queued]
    root.followup_agents = [coder, queued]

    assert current_family_shell_row(root) is coder


def test_current_family_shell_selects_nested_running_monitor() -> None:
    root = _agent("alpha--0", role="root", status="DONE", stop_offset=1)
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="DONE",
        start_offset=2,
        stop_offset=3,
    )
    monitor = _monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-running",
        monitor_state="running",
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]

    assert current_family_shell_row(root) is monitor


def test_current_family_shell_returns_none_without_active_shell() -> None:
    root = _agent("alpha--0", role="root", status="DONE", stop_offset=1)
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="DONE",
        start_offset=2,
        stop_offset=3,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert current_family_shell_row(root) is None


def test_current_family_shell_ignores_waiting_and_parallel_families() -> None:
    root = _agent("alpha--0", role="root", status="DONE", stop_offset=1)
    waiting = _agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="WAITING",
        start_offset=2,
    )
    root.runtime_children = [waiting]
    root.followup_agents = [waiting]

    parallel = _agent("parallel", role="root", status="RUNNING")
    parallel.agent_family_parallel = True
    parallel_child = _agent(
        "parallel--1",
        role="phase",
        parent_timestamp=parallel.raw_suffix,
        status="RUNNING",
    )
    parallel_child.agent_family_parallel = True
    parallel.runtime_children = [parallel_child]
    parallel.followup_agents = [parallel_child]

    assert current_family_shell_row(root) is None
    assert current_family_shell_row(parallel) is None


def test_current_family_shell_uses_newest_active_candidate_in_chain_order() -> None:
    root = _agent("alpha--0", role="root", status="RUNNING")
    coder = _agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="RUNNING",
        start_offset=1,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert current_family_shell_row(root) is coder

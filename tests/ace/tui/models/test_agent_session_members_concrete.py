"""Concrete member-row tests for sequential agent sessions.

Plan-root replacement, workflow aggregates, and the sequential container
predicate for the concrete agent session-member projection.
"""

from __future__ import annotations

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_session_members import (
    _concrete_agent_rows,
    concrete_agent_session_member_rows,
    concrete_agent_statuses,
    is_sequential_agent_session_container,
)
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_plan_root,
)

__all__ = [
    "test_bare_non_plan_container_stays_execution_neutral",
    "test_concrete_planner_replaces_aggregate_root_and_mixed_links_dedupe",
    "test_member_plus_monitor_still_makes_a_agent_session_container",
    "test_monitor_only_child_does_not_make_starter_a_agent_session_container",
    "test_plan_root_without_concrete_planner_uses_root_fallback",
    "test_promoted_plan_agent_session_root_no_longer_double_counted_as_member",
    "test_rename_on_attach_root_remains_the_first_real_member",
    "test_workflow_aggregate_projects_only_loaded_agent_steps",
    "test_workflow_without_loaded_agent_steps_falls_back_to_root",
]


def test_concrete_planner_replaces_aggregate_root_and_mixed_links_dedupe() -> None:
    root = make_plan_root()
    planner = make_agent(
        "alpha--plan-step",
        role="plan",
        parent_timestamp=root.raw_suffix,
        workflow_child=True,
    )
    feedback = make_agent(
        "alpha--2",
        role="feedback",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    parallel = make_agent(
        "alpha--parallel",
        role="review",
        parent_timestamp=root.raw_suffix,
    )
    parallel.agent_session_parallel = True

    root.runtime_children = [planner, feedback, coder, parallel]
    root.followup_agents = [feedback, coder, parallel]

    assert concrete_agent_session_member_rows(root) == (planner, feedback, coder)


def test_rename_on_attach_root_remains_the_first_real_member() -> None:
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert concrete_agent_session_member_rows(root) == (root, coder)


def test_promoted_plan_agent_session_root_no_longer_double_counted_as_member() -> None:
    """A derived plan-session root's main step, not the root, is member #0.

    Mirrors the 'pv' bug agent_session: a root promoted to '--0' (plan_chain_root
    stays False) whose plan chain only started later in a member. Once
    ``derived_plan_agent_session_root`` is set, the root must stop standing in as
    member #0 or the lane header's "N agents · M awaiting" count double-counts
    it alongside the mirrored status.
    """
    root = make_agent("pv", role="root")
    root.role_suffix = "--0"
    root.derived_plan_agent_session_root = True
    main_step = make_agent(
        "pv--0",
        role="q",
        parent_timestamp=root.raw_suffix,
        workflow_child=True,
        status="ANSWERED",
        stop_offset=1,
    )
    plan_member = make_agent(
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
    root = make_plan_root(name="alpha")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert concrete_agent_session_member_rows(root) == (root, coder)


def test_bare_non_plan_container_stays_execution_neutral() -> None:
    root = make_agent("alpha", role="root")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
    )
    root.followup_agents = [coder]

    assert concrete_agent_session_member_rows(root) == (coder,)


def test_workflow_aggregate_projects_only_loaded_agent_steps() -> None:
    root = make_agent("workflow", role="root")
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    main = make_agent(
        "workflow-main",
        role="main",
        workflow_child=True,
    )
    python_step = make_agent(
        "workflow-python",
        role="python",
        workflow_child=True,
        step_type="python",
    )
    root.runtime_children = [main, python_step]

    assert _concrete_agent_rows(root) == (main,)
    assert _concrete_agent_rows(python_step) == ()


def test_workflow_without_loaded_agent_steps_falls_back_to_root() -> None:
    root = make_agent("workflow", role="root")
    root.agent_type = AgentType.WORKFLOW
    root.workflow = "demo"
    python_step = make_agent(
        "workflow-python",
        role="python",
        workflow_child=True,
        step_type="python",
    )
    root.runtime_children = [python_step]

    assert _concrete_agent_rows(root) == (root,)


def test_monitor_only_child_does_not_make_starter_a_agent_session_container() -> None:
    starter = make_agent("alpha--2", role="code")
    monitor = make_agent(
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

    assert is_sequential_agent_session_container(starter) is False


def test_member_plus_monitor_still_makes_a_agent_session_container() -> None:
    starter = make_agent("alpha--2", role="code")
    continuation = make_agent(
        "alpha--3",
        role="code",
        parent_timestamp=starter.raw_suffix,
        start_offset=1,
    )
    monitor = make_agent(
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

    assert is_sequential_agent_session_container(starter) is True

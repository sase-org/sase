"""Tests for feedback follow-up status override behavior."""

from datetime import datetime

from sase.agent.status_buckets import (
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_TALE_STATUS,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_feedback_child_unreviewed_plan_stays_done() -> None:
    """A feedback child without a gate no longer reconstructs pending PLAN."""
    feedback_time = datetime(2026, 5, 17, 9, 0, 0)
    plan_time = datetime(2026, 5, 17, 9, 10, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="-plan",
        agent_name="root",
        agent_family="root",
        agent_family_role="root",
        plan_chain_root=True,
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 9, 5, 0),
        parent_timestamp="20260517085500",
        role_suffix="-2",
        feedback_times=[feedback_time],
        plan_times=[plan_time],
    )

    _apply_status_overrides([parent, feedback_child])

    assert feedback_child.status == "DONE"
    assert parent.status == "DONE"


def test_apply_status_overrides_new_plan_feedback_child_without_gate_stays_done() -> (
    None
):
    """A '--plan-0' replan child no longer reconstructs pending PLAN."""
    feedback_time = datetime(2026, 5, 17, 9, 0, 0)
    plan_time = datetime(2026, 5, 17, 9, 10, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="-plan",
        agent_name="root",
        agent_family="root",
        agent_family_role="root",
        plan_chain_root=True,
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 9, 5, 0),
        parent_timestamp="20260517085500",
        role_suffix="--plan-0",
        agent_family_role="feedback",
        feedback_times=[feedback_time],
        plan_times=[plan_time],
    )

    _apply_status_overrides([parent, feedback_child])

    assert feedback_child.status == "DONE"
    assert parent.status == "DONE"


def test_apply_status_overrides_feedback_child_approved_by_metadata_shows_approved() -> (
    None
):
    """A feedback child with approved-plan metadata shows sticky approval."""
    feedback_time = datetime(2026, 5, 17, 9, 0, 0)
    plan_time = datetime(2026, 5, 17, 9, 10, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="-plan",
        agent_name="root",
        agent_family="root",
        agent_family_role="root",
        plan_chain_root=True,
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 9, 5, 0),
        parent_timestamp="20260517085500",
        role_suffix="-2",
        feedback_times=[feedback_time],
        plan_times=[plan_time],
        plan_action="approve",
    )

    _apply_status_overrides([parent, feedback_child])

    assert feedback_child.status == PLAN_APPROVED_STATUS
    assert parent.status == PLAN_APPROVED_STATUS


def test_apply_status_overrides_feedback_child_after_code_handoff_shows_approved() -> (
    None
):
    """An approved feedback child keeps approval while root mirrors active code."""
    feedback_time = datetime(2026, 5, 17, 9, 0, 0)
    plan_time = datetime(2026, 5, 17, 9, 10, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="-plan",
        agent_name="root",
        agent_family="root",
        agent_family_role="root",
        plan_chain_root=True,
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 9, 5, 0),
        parent_timestamp="20260517085500",
        role_suffix="-2",
        feedback_times=[feedback_time],
        plan_times=[plan_time],
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 17, 9, 20, 0),
        parent_timestamp="20260517085500",
        role_suffix="-code",
        agent_name="root-code",
        agent_family="root",
        agent_family_role="code",
        plan_action="tale",
    )

    _apply_status_overrides([parent, feedback_child, code_child])

    assert feedback_child.status == TALE_APPROVED_STATUS
    assert code_child.status == WORKING_TALE_STATUS
    assert parent.status == WORKING_TALE_STATUS


def test_apply_status_overrides_plan_rejected_stays_terminal() -> None:
    """A rejected plan is terminal, not another plan awaiting approval."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="PLAN REJECTED",
        start_time=datetime(2026, 4, 17, 16, 33, 26),
        raw_suffix="20260417163326",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 45, 16),
        parent_timestamp="20260417163326",
        role_suffix=".2",
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.status == "DONE"

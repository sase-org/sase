"""Tests for feedback follow-up status override behavior."""

from datetime import datetime

from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_TALE_STATUS,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_feedback_child_awaiting_review_mirrors_plan() -> None:
    """A feedback round that submitted a newer plan becomes the mirrored root status."""
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

    assert feedback_child.status == "PLAN"
    assert parent.status == "PLAN"


def test_apply_status_overrides_new_plan_feedback_child_awaiting_review() -> None:
    """A '--plan-0' replan child is treated as feedback, not a root question."""
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

    assert feedback_child.status == "PLAN"
    assert parent.status == "PLAN"


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


def test_apply_status_overrides_superseded_first_planner_shows_feedback() -> None:
    """A first planner superseded by a feedback round is not stale-approved."""
    p1 = datetime(2026, 6, 28, 13, 29, 35)
    f1 = datetime(2026, 6, 28, 13, 36, 5)
    p2 = datetime(2026, 6, 28, 13, 47, 25)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 28, 13, 17, 57),
        run_start_time=datetime(2026, 6, 28, 13, 17, 57),
        raw_suffix="20260628131757",
        role_suffix="--plan",
        agent_name="08w",
        agent_family="08w",
        agent_family_role="root",
        plan_chain_root=True,
        plan_times=[p1],
        feedback_times=[f1],
        plan_action="tale",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 28, 13, 36, 8),
        run_start_time=datetime(2026, 6, 28, 13, 36, 8),
        raw_suffix="20260628133608",
        parent_timestamp="20260628131757",
        role_suffix="--plan-0",
        agent_name="08w--plan-0",
        agent_family="08w",
        agent_family_role="feedback",
        feedback_times=[f1],
        plan_times=[p2],
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 6, 28, 13, 48, 17),
        run_start_time=datetime(2026, 6, 28, 13, 48, 17),
        raw_suffix="20260628134817",
        parent_timestamp="20260628131757",
        role_suffix="--code",
        agent_name="08w--code",
        agent_family="08w",
        agent_family_role="code",
        plan_action="tale",
    )
    agents = [parent, feedback_child, code_child]

    _apply_status_overrides(agents)

    planner = next(a for a in agents if a.agent_name == "08w--plan")
    assert planner.status == FEEDBACK_STATUS
    assert planner.plan_times == [p1]
    assert feedback_child.status == TALE_APPROVED_STATUS
    assert code_child.status == WORKING_TALE_STATUS
    assert parent.status == WORKING_TALE_STATUS


def test_apply_status_overrides_multi_round_feedback_marks_superseded_rounds() -> None:
    """Each planner round with a later planner-family sibling shows FEEDBACK."""
    p1 = datetime(2026, 6, 28, 9, 5, 0)
    f1 = datetime(2026, 6, 28, 9, 10, 0)
    p2 = datetime(2026, 6, 28, 9, 20, 0)
    f2 = datetime(2026, 6, 28, 9, 25, 0)
    p3 = datetime(2026, 6, 28, 9, 35, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 28, 9, 0, 0),
        run_start_time=datetime(2026, 6, 28, 9, 0, 0),
        raw_suffix="20260628090000",
        role_suffix="--plan",
        agent_name="mr",
        agent_family="mr",
        agent_family_role="root",
        plan_chain_root=True,
        plan_times=[p1],
        feedback_times=[f1],
    )
    feedback_0 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 28, 9, 10, 5),
        run_start_time=datetime(2026, 6, 28, 9, 10, 5),
        raw_suffix="20260628091005",
        parent_timestamp="20260628090000",
        role_suffix="--plan-0",
        agent_name="mr--plan-0",
        agent_family="mr",
        agent_family_role="feedback",
        feedback_times=[f1, f2],
        plan_times=[p2],
    )
    feedback_1 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 28, 9, 25, 5),
        run_start_time=datetime(2026, 6, 28, 9, 25, 5),
        raw_suffix="20260628092505",
        parent_timestamp="20260628090000",
        role_suffix="--plan-1",
        agent_name="mr--plan-1",
        agent_family="mr",
        agent_family_role="feedback",
        feedback_times=[f2],
        plan_times=[p3],
        plan_action="approve",
    )
    agents = [parent, feedback_0, feedback_1]

    _apply_status_overrides(agents)

    planner = next(a for a in agents if a.agent_name == "mr--plan")
    assert planner.status == FEEDBACK_STATUS
    assert feedback_0.status == FEEDBACK_STATUS
    assert feedback_1.status == PLAN_APPROVED_STATUS
    assert parent.status == PLAN_APPROVED_STATUS


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

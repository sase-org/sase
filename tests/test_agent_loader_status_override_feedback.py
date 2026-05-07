"""Tests for _apply_status_overrides feedback timestamp propagation."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_done_with_active_feedback_becomes_running() -> None:
    """A DONE .plan parent with an active feedback child is marked RUNNING."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 33, 26),
        raw_suffix="20260417163326",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 17, 16, 45, 16),
        parent_timestamp="20260417163326",
        role_suffix=".2",
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.status == "RUNNING"


def test_apply_status_overrides_done_with_completed_feedback_becomes_planning() -> None:
    """A DONE .plan parent with only completed feedback falls through to PLANNING."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 33, 26),
        raw_suffix="20260417163326",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 45, 16),
        parent_timestamp="20260417163326",
        role_suffix=".2",
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLANNING"


def test_apply_status_overrides_deduplicates_feedback_child_feedback_time() -> None:
    """Parent and feedback child holding the same feedback time render one event."""
    feedback_time = datetime(2026, 5, 6, 0, 16, 35)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 12, 45),
        raw_suffix="20260506001245",
        role_suffix=".plan",
        feedback_times=[feedback_time],
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 16, 35),
        parent_timestamp="20260506001245",
        role_suffix=".2",
        feedback_times=[feedback_time],
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.feedback_times == [feedback_time]
    assert parent.timestamps_display.count("FBACK") == 1


def test_apply_status_overrides_propagates_feedback_plan_path() -> None:
    """Feedback child rejected plan paths propagate to the root plan parent."""
    feedback_time = datetime(2026, 5, 6, 0, 16, 35)
    plan_path = "/tmp/rejected-plan.md"
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 12, 45),
        raw_suffix="20260506001245",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 16, 35),
        parent_timestamp="20260506001245",
        role_suffix=".2",
        feedback_times=[feedback_time],
        feedback_plan_paths={feedback_time: plan_path},
    )

    _apply_status_overrides([parent, feedback_child])

    assert parent.feedback_times == [feedback_time]
    assert parent.feedback_plan_paths == {feedback_time: plan_path}


def test_apply_status_overrides_feedback_plan_path_is_idempotent() -> None:
    """Reapplying overrides does not duplicate or change propagated path data."""
    feedback_time = datetime(2026, 5, 6, 0, 16, 35)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 12, 45),
        raw_suffix="20260506001245",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 16, 35),
        parent_timestamp="20260506001245",
        role_suffix=".2",
        feedback_times=[feedback_time],
        feedback_plan_paths={feedback_time: "/tmp/rejected-plan.md"},
    )
    agents = [parent, feedback_child]

    _apply_status_overrides(agents)
    _apply_status_overrides(agents)

    assert parent.feedback_times == [feedback_time]
    assert parent.feedback_plan_paths == {feedback_time: "/tmp/rejected-plan.md"}


def test_apply_status_overrides_keeps_parent_feedback_plan_path() -> None:
    """A child without path metadata does not clear an existing parent path."""
    feedback_time = datetime(2026, 5, 6, 0, 16, 35)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 12, 45),
        raw_suffix="20260506001245",
        role_suffix=".plan",
        feedback_times=[feedback_time],
        feedback_plan_paths={feedback_time: "/tmp/parent-plan.md"},
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 16, 35),
        parent_timestamp="20260506001245",
        role_suffix=".2",
        feedback_times=[feedback_time],
    )

    _apply_status_overrides([parent, feedback_child])

    assert parent.feedback_plan_paths == {feedback_time: "/tmp/parent-plan.md"}


def test_apply_status_overrides_propagates_new_feedback_child_plan_time() -> None:
    """A feedback child plan submission still propagates when it is distinct."""
    original_plan_time = datetime(2026, 5, 6, 0, 13, 0)
    feedback_plan_time = datetime(2026, 5, 6, 0, 20, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 12, 45),
        raw_suffix="20260506001245",
        role_suffix=".plan",
        plan_times=[original_plan_time],
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 16, 35),
        parent_timestamp="20260506001245",
        role_suffix=".2",
        plan_times=[feedback_plan_time],
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.plan_times == [original_plan_time, feedback_plan_time]


def test_apply_status_overrides_timestamp_propagation_is_idempotent() -> None:
    """Reapplying overrides does not duplicate child timestamps on the parent."""
    feedback_time = datetime(2026, 5, 6, 0, 16, 35)
    question_time = datetime(2026, 5, 6, 0, 18, 0)
    plan_time = datetime(2026, 5, 6, 0, 20, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 12, 45),
        raw_suffix="20260506001245",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 6, 0, 16, 35),
        parent_timestamp="20260506001245",
        role_suffix=".2",
        plan_times=[plan_time],
        feedback_times=[feedback_time],
        questions_times=[question_time],
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)
    _apply_status_overrides(agents)

    assert parent.plan_times == [plan_time]
    assert parent.feedback_times == [feedback_time]
    assert parent.questions_times == [question_time]

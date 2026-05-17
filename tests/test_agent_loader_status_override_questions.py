"""Tests for _apply_status_overrides question status decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_done_with_unanswered_question_becomes_question() -> (
    None
):
    """A DONE agent with questions_times and no .q follow-up becomes QUESTION."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
        questions_times=[datetime(2026, 4, 21, 16, 17, 4)],
    )
    agents = [agent]
    _apply_status_overrides(agents)

    assert agent.status == "QUESTION"


def test_apply_status_overrides_done_with_answered_question_stays_done() -> None:
    """A DONE agent with a .q follow-up stays DONE (question was answered)."""
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
        questions_times=[datetime(2026, 4, 21, 16, 17, 4)],
    )
    q_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 20, 0),
        parent_timestamp="20260421160427",
        role_suffix=".q",
    )
    agents = [parent, q_child]
    _apply_status_overrides(agents)

    assert parent.status == "DONE"


def test_apply_status_overrides_parent_with_questioning_code_child_becomes_question() -> (
    None
):
    """A DONE .plan parent whose .code child has an unanswered question becomes QUESTION."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        raw_suffix="20260511091000",
        parent_timestamp="20260511090000",
        role_suffix=".code",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "QUESTION"
    assert code_child.status == "QUESTION"


def test_apply_status_overrides_parent_with_answered_question_stays_plan_done() -> None:
    """A DONE .plan parent whose .code child's question was answered (has .q follow-up) stays PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        raw_suffix="20260511091000",
        parent_timestamp="20260511090000",
        role_suffix=".code",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    q_grandchild = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 40, 0),
        parent_timestamp="20260511091000",
        role_suffix=".q",
    )
    agents = [parent, code_child, q_grandchild]
    _apply_status_overrides(agents)

    assert parent.status == "DONE"


def test_apply_status_overrides_parent_with_active_code_after_question_is_plan_approved() -> (
    None
):
    """An active .code child (answer in flight) keeps the parent at PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        raw_suffix="20260511091000",
        parent_timestamp="20260511090000",
        role_suffix=".code",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "RUNNING"


def test_apply_status_overrides_questioning_code_with_tale_plan_action_still_becomes_question() -> (
    None
):
    """A parent with plan_action=tale whose .code child has an unanswered question still becomes QUESTION."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        raw_suffix="20260511091000",
        parent_timestamp="20260511090000",
        role_suffix=".code",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "QUESTION"


def test_apply_status_overrides_done_without_questions_stays_done() -> None:
    """A DONE agent with empty questions_times stays DONE."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
    )
    agents = [agent]
    _apply_status_overrides(agents)

    assert agent.status == "DONE"

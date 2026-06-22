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


def test_apply_status_overrides_done_with_recorded_question_response_stays_done() -> (
    None
):
    """A DONE row with persisted response metadata is not still awaiting input."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
        questions_times=[datetime(2026, 4, 21, 16, 17, 4)],
        question_response_path="/tmp/question_response.json",
    )
    agents = [agent]
    _apply_status_overrides(agents)

    assert agent.status == "DONE"


def test_apply_status_overrides_planner_child_with_answered_family_followup_is_done() -> (
    None
):
    """A later family follow-up proves the planner question was answered."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 29, 9, 0, 0),
        raw_suffix="20260529090000",
        role_suffix="-plan",
        agent_name="ap1",
        agent_family="ap1",
        agent_family_role="root",
        plan_chain_root=True,
        plan_times=[datetime(2026, 5, 29, 9, 10, 0)],
        questions_times=[datetime(2026, 5, 29, 9, 15, 0)],
    )
    planner_child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 29, 9, 0, 0),
        raw_suffix="20260529090000",
        parent_workflow="my_cl",
        parent_timestamp="20260529090000",
        step_type="agent",
        step_index=0,
        total_steps=2,
        role_suffix="-plan",
        agent_name="ap1-plan",
        agent_family="ap1",
        agent_family_role="plan",
    )
    followup_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 29, 9, 20, 0),
        raw_suffix="20260529092000",
        parent_timestamp="20260529090000",
        role_suffix="-2",
        agent_name="ap1-2",
        agent_family="ap1",
        agent_family_role="feedback",
    )
    agents = [parent, followup_child]
    _apply_status_overrides(agents, [planner_child])

    assert planner_child.status == "DONE"
    assert parent.status == "DONE"


def test_apply_status_overrides_answered_question_only_family_is_done() -> None:
    """An answered root-question family shows DONE with an ANSWERED asker row."""
    question_time = datetime(2026, 6, 19, 15, 46, 14, 861080)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 19, 10, 2, 17),
        raw_suffix="20260619100217",
        role_suffix="--0",
        agent_name="sase-4z.5",
        agent_family="sase-4z.5",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[question_time],
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 19, 11, 46, 16),
        raw_suffix="20260619114616",
        parent_timestamp="20260619100217",
        role_suffix="--1",
        agent_name="sase-4z.5--1",
        agent_family="sase-4z.5",
        agent_family_role="q",
        questions_times=[question_time],
    )
    agents = [parent, continuation]

    _apply_status_overrides(agents)

    asker = next(
        agent
        for agent in agents
        if agent.parent_timestamp == parent.raw_suffix and agent.role_suffix == "--0"
    )
    assert continuation.status == "DONE"
    assert parent.status == "DONE"
    assert asker.status == "ANSWERED"


def test_apply_status_overrides_inherited_question_with_new_round_is_question() -> None:
    """A continuation with a new unanswered question timestamp remains blocked."""
    first_question_time = datetime(2026, 6, 19, 15, 46, 14)
    second_question_time = datetime(2026, 6, 19, 16, 20, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 19, 10, 2, 17),
        raw_suffix="20260619100217",
        role_suffix="--0",
        agent_name="sase-4z.5",
        agent_family="sase-4z.5",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[first_question_time],
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 19, 11, 46, 16),
        raw_suffix="20260619114616",
        parent_timestamp="20260619100217",
        role_suffix="--1",
        agent_name="sase-4z.5--1",
        agent_family="sase-4z.5",
        agent_family_role="q",
        questions_times=[first_question_time, second_question_time],
    )
    agents = [parent, continuation]

    _apply_status_overrides(agents)

    assert continuation.status == "QUESTION"
    assert parent.status == "QUESTION"


def test_apply_status_overrides_question_only_family_without_followup_is_question() -> (
    None
):
    """A question-only family with no continuation still waits for user input."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 19, 10, 2, 17),
        raw_suffix="20260619100217",
        role_suffix="--0",
        agent_name="sase-4z.5",
        agent_family="sase-4z.5",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[datetime(2026, 6, 19, 15, 46, 14)],
    )
    agents = [parent]

    _apply_status_overrides(agents)

    asker = next(
        agent
        for agent in agents
        if agent.parent_timestamp == parent.raw_suffix and agent.role_suffix == "--0"
    )
    assert parent.status == "QUESTION"
    assert asker.status == "QUESTION"


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

    assert parent.status == "PLAN DONE"
    assert code_child.status == "PLAN DONE"


def test_apply_status_overrides_parent_with_active_code_after_question_is_working_plan() -> (
    None
):
    """An active .code child (answer in flight) makes the parent WORKING PLAN."""
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

    assert parent.status == "WORKING PLAN"
    assert code_child.status == "WORKING PLAN"


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


def test_apply_status_overrides_numeric_answered_continuation_is_plan_done() -> None:
    """A completed numeric family continuation with a response path is terminal."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix="-plan",
        agent_name="aj5",
        agent_family="aj5",
        agent_family_role="root",
        plan_chain_root=True,
    )
    latest_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 40, 0),
        raw_suffix="20260511094000",
        parent_timestamp="20260511090000",
        role_suffix="-5",
        agent_name="aj5-5",
        agent_family="aj5",
        agent_family_role="feedback",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
        question_response_path="/tmp/question_response.json",
    )
    agents = [parent, latest_child]
    _apply_status_overrides(agents)

    assert latest_child.status == "PLAN DONE"
    assert parent.status == "PLAN DONE"


def test_apply_status_overrides_root_numeric_question_is_not_feedback_done() -> None:
    """A '--2' root question row with q metadata is not legacy feedback."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix="--0",
        agent_name="aj5",
        agent_family="aj5",
        agent_family_role="root",
        plan_chain_root=True,
    )
    latest_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 40, 0),
        raw_suffix="20260511094000",
        parent_timestamp="20260511090000",
        role_suffix="--2",
        agent_name="aj5--2",
        agent_family="aj5",
        agent_family_role="q",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
        question_response_path="/tmp/question_response.json",
    )
    agents = [parent, latest_child]
    _apply_status_overrides(agents)

    assert latest_child.status == "DONE"
    assert parent.status == "DONE"


def test_apply_status_overrides_numeric_unanswered_continuation_is_question() -> None:
    """A completed numeric family continuation without a response remains blocked."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix="-plan",
        agent_name="aj5",
        agent_family="aj5",
        agent_family_role="root",
        plan_chain_root=True,
    )
    latest_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 40, 0),
        raw_suffix="20260511094000",
        parent_timestamp="20260511090000",
        role_suffix="-5",
        agent_name="aj5-5",
        agent_family="aj5",
        agent_family_role="feedback",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    agents = [parent, latest_child]
    _apply_status_overrides(agents)

    assert latest_child.status == "QUESTION"
    assert parent.status == "QUESTION"

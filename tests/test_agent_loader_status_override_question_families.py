"""Tests for _apply_status_overrides question family status decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_plan_suffix_inherited_question_stays_done() -> None:
    """A --plan continuation with only the inherited parent question is not QUESTION."""
    question_time = datetime(2026, 6, 23, 7, 5, 49)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 6, 57, 2),
        raw_suffix="20260623065702",
        role_suffix="--0",
        agent_name="sase-03w",
        agent_family="sase-03w",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[question_time],
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 7, 5, 50),
        raw_suffix="20260623070550",
        parent_timestamp="20260623065702",
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="agent",
        questions_times=[question_time],
    )
    agents = [parent, continuation]

    _apply_status_overrides(agents)

    assert continuation.status == "DONE"
    assert parent.status == "DONE"


def test_apply_status_overrides_plan_suffix_new_question_round_is_question() -> None:
    """A --plan continuation with a new unanswered question remains blocked."""
    first_question_time = datetime(2026, 6, 23, 7, 5, 49)
    second_question_time = datetime(2026, 6, 23, 7, 12, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 6, 57, 2),
        raw_suffix="20260623065702",
        role_suffix="--0",
        agent_name="sase-03w",
        agent_family="sase-03w",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[first_question_time],
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 7, 5, 50),
        raw_suffix="20260623070550",
        parent_timestamp="20260623065702",
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="agent",
        questions_times=[first_question_time, second_question_time],
    )
    agents = [parent, continuation]

    _apply_status_overrides(agents)

    assert continuation.status == "QUESTION"
    assert parent.status == "QUESTION"


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
        agent_family_role="agent",
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
    """A DONE .plan parent with an answered .code child question stays PLAN DONE."""
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
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 40, 0),
        parent_timestamp="20260511091000",
        role_suffix="--1",
    )
    agents = [parent, code_child, continuation]
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
    """An unanswered .code child question still overrides plan_action=tale."""
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


def test_apply_status_overrides_ordinary_answered_continuation_is_done() -> None:
    """An ordinary answered continuation is not treated as plan feedback."""
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
        role_suffix="--1",
        agent_name="aj5--1",
        agent_family="aj5",
        agent_family_role="agent",
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
        role_suffix="--1",
        agent_name="aj5--1",
        agent_family="aj5",
        agent_family_role="agent",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    agents = [parent, latest_child]
    _apply_status_overrides(agents)

    assert latest_child.status == "QUESTION"
    assert parent.status == "QUESTION"

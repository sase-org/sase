"""Tests for question-continuation status overrides."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def _question_continuation_family_root() -> tuple[Agent, Agent]:
    root_start = datetime(2026, 6, 30, 0, 0, 0)
    first_question_time = datetime(2026, 6, 30, 0, 3, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix="20260630000000",
        role_suffix="--0",
        agent_name="0am",
        agent_family="0am",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[first_question_time],
    )
    root_asker = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix=parent.raw_suffix,
        parent_workflow="ace-run",
        parent_timestamp=parent.raw_suffix,
        step_type="agent",
        role_suffix="--0",
        agent_name="0am--0",
        agent_family="0am",
        agent_family_role="q",
    )
    return parent, root_asker


def _question_continuation(
    parent: Agent,
    *,
    raw_suffix: str,
    role_suffix: str,
    start_time: datetime,
    status: str = "DONE",
    question_time: datetime | None = None,
    response_path: str | None = None,
) -> Agent:
    questions_times = [question_time] if question_time else []
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status=status,
        start_time=start_time,
        run_start_time=start_time,
        raw_suffix=raw_suffix,
        parent_timestamp=parent.raw_suffix,
        role_suffix=role_suffix,
        agent_name=f"0am{role_suffix}",
        agent_family="0am",
        agent_family_role="q",
        questions_times=questions_times,
        question_response_path=response_path,
    )


def test_apply_status_overrides_answered_question_continuation_asker() -> None:
    """A q continuation that was answered and handed off shows ANSWERED."""
    second_question_time = datetime(2026, 6, 30, 0, 12, 0)
    parent, root_asker = _question_continuation_family_root()
    first_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001000",
        role_suffix="--1",
        start_time=datetime(2026, 6, 30, 0, 10, 0),
        question_time=second_question_time,
        response_path="/tmp/question-2-response.json",
    )
    active_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001400",
        role_suffix="--2",
        start_time=datetime(2026, 6, 30, 0, 14, 0),
        status="RUNNING",
        question_time=second_question_time,
    )

    _apply_status_overrides(
        [parent, first_continuation, active_continuation],
        [root_asker],
    )

    assert root_asker.status == "ANSWERED"
    assert first_continuation.status == "ANSWERED"
    assert first_continuation.stop_time == second_question_time
    assert active_continuation.status == "RUNNING"
    assert parent.status == "RUNNING"


def test_apply_status_overrides_question_continuation_before_answer_is_question() -> (
    None
):
    """A completed q continuation with no response still waits for the user."""
    second_question_time = datetime(2026, 6, 30, 0, 12, 0)
    parent, root_asker = _question_continuation_family_root()
    first_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001000",
        role_suffix="--1",
        start_time=datetime(2026, 6, 30, 0, 10, 0),
        question_time=second_question_time,
    )

    _apply_status_overrides([parent, first_continuation], [root_asker])

    assert first_continuation.status == "QUESTION"


def test_apply_status_overrides_final_question_continuation_stays_done() -> None:
    """The final answered continuation stays DONE when no newer sibling exists."""
    second_question_time = datetime(2026, 6, 30, 0, 12, 0)
    parent, root_asker = _question_continuation_family_root()
    first_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001000",
        role_suffix="--1",
        start_time=datetime(2026, 6, 30, 0, 10, 0),
        question_time=second_question_time,
        response_path="/tmp/question-2-response.json",
    )
    final_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001400",
        role_suffix="--2",
        start_time=datetime(2026, 6, 30, 0, 14, 0),
        question_time=second_question_time,
        response_path="/tmp/question-2-response.json",
    )

    _apply_status_overrides(
        [parent, first_continuation, final_continuation],
        [root_asker],
    )

    assert first_continuation.status == "ANSWERED"
    assert final_continuation.status == "DONE"


def test_apply_status_overrides_deep_question_continuation_chain() -> None:
    """Each handed-off q continuation is ANSWERED in a deeper question chain."""
    second_question_time = datetime(2026, 6, 30, 0, 12, 0)
    third_question_time = datetime(2026, 6, 30, 0, 18, 0)
    parent, root_asker = _question_continuation_family_root()
    first_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001000",
        role_suffix="--1",
        start_time=datetime(2026, 6, 30, 0, 10, 0),
        question_time=second_question_time,
        response_path="/tmp/question-2-response.json",
    )
    second_continuation = _question_continuation(
        parent,
        raw_suffix="20260630001400",
        role_suffix="--2",
        start_time=datetime(2026, 6, 30, 0, 14, 0),
        question_time=third_question_time,
        response_path="/tmp/question-3-response.json",
    )
    active_continuation = _question_continuation(
        parent,
        raw_suffix="20260630002000",
        role_suffix="--3",
        start_time=datetime(2026, 6, 30, 0, 20, 0),
        status="RUNNING",
        question_time=third_question_time,
    )

    _apply_status_overrides(
        [parent, first_continuation, second_continuation, active_continuation],
        [root_asker],
    )

    assert first_continuation.status == "ANSWERED"
    assert second_continuation.status == "ANSWERED"
    assert active_continuation.status == "RUNNING"


def _question_continuation_planner_family(
    *,
    plan_action: str = "tale",
) -> tuple[Agent, Agent, Agent]:
    question_time = datetime(2026, 6, 23, 7, 5, 49)
    plan_time = datetime(2026, 6, 23, 7, 6, 42)
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
    continuation_planner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 7, 5, 50),
        run_start_time=datetime(2026, 6, 23, 7, 5, 50),
        raw_suffix="20260623070550",
        parent_timestamp="20260623065702",
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="q",
        questions_times=[question_time],
        plan_times=[plan_time],
        plan_action=plan_action,
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 6, 23, 7, 7, 10),
        run_start_time=datetime(2026, 6, 23, 7, 7, 10),
        raw_suffix="20260623070710",
        parent_timestamp="20260623065702",
        role_suffix="--code",
        agent_name="sase-03w--code",
        agent_family="sase-03w",
        agent_family_role="code",
    )
    return parent, continuation_planner, coder


def test_apply_status_overrides_question_continuation_planner_family() -> None:
    """A question continuation that approved a tale plan keeps each row's own state."""
    parent, continuation_planner, coder = _question_continuation_planner_family()
    agents = [parent, continuation_planner, coder]

    _apply_status_overrides(agents)

    asker = next(
        agent
        for agent in agents
        if agent.parent_timestamp == parent.raw_suffix and agent.role_suffix == "--0"
    )
    assert asker.status == "ANSWERED"
    assert continuation_planner.status == "TALE APPROVED"
    assert coder.status == "WORKING PLAN"
    assert parent.status == "WORKING PLAN"


def test_apply_status_overrides_question_continuation_planner_approve_action() -> None:
    """A question continuation with approve action becomes PLAN APPROVED."""
    parent, continuation_planner, coder = _question_continuation_planner_family(
        plan_action="approve"
    )
    agents = [parent, continuation_planner, coder]

    _apply_status_overrides(agents)

    asker = next(
        agent
        for agent in agents
        if agent.parent_timestamp == parent.raw_suffix and agent.role_suffix == "--0"
    )
    assert asker.status == "ANSWERED"
    assert continuation_planner.status == "PLAN APPROVED"
    assert coder.status == "WORKING PLAN"
    assert parent.status == "WORKING PLAN"

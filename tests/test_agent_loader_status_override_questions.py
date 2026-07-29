"""Tests for _apply_status_overrides question status decisions."""

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType, compute_row_runtime
from sase.ace.tui.models.agent_time import runtime_suffix_ticks
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
    assert asker.stop_time == question_time


def _rename_on_attach_root_step(
    *,
    question_response_path: str | None,
) -> tuple[Agent, Agent]:
    root_start = datetime(2026, 7, 29, 6, 22, 53)
    question_time = datetime(2026, 7, 29, 6, 27, 18, 856220)
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix="20260729062253",
        role_suffix="--0",
        agent_name="nr--0",
        agent_family="nr",
        agent_family_role="root",
        plan_chain_root=False,
        questions_times=[question_time],
        question_response_path=question_response_path,
    )
    root_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=datetime(2026, 7, 29, 6, 23, 20),
        raw_suffix=root.raw_suffix,
        parent_workflow="ace-run",
        parent_timestamp=root.raw_suffix,
        step_name="main",
        step_type="agent",
        parent_step_index=None,
        role_suffix="--0",
        agent_name="nr--0",
        agent_family="nr",
        agent_family_role="q",
        questions_times=[question_time],
        question_response_path=question_response_path,
    )
    return root, root_step


def test_apply_status_overrides_rename_on_attach_root_step_is_answered() -> None:
    """A handed-off rename-on-attach root step shows ANSWERED."""
    root, root_step = _rename_on_attach_root_step(
        question_response_path="/tmp/question-response.json"
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 29, 6, 30, 58),
        run_start_time=datetime(2026, 7, 29, 6, 30, 58),
        raw_suffix="20260729063058",
        parent_timestamp=root.raw_suffix,
        role_suffix="--1",
        agent_name="nr--1",
        agent_family="nr",
        agent_family_role="q",
    )

    _apply_status_overrides([root, continuation], [root_step])

    assert root_step.status == "ANSWERED"
    assert root_step.stop_time == max(root_step.questions_times)
    assert root.status == "RUNNING"
    assert continuation.status == "RUNNING"


def test_apply_status_overrides_rename_on_attach_root_step_without_response_is_question() -> (
    None
):
    """An unanswered rename-on-attach root step remains QUESTION."""
    root, root_step = _rename_on_attach_root_step(question_response_path=None)

    _apply_status_overrides([root], [root_step])

    assert root_step.status == "QUESTION"


def test_apply_status_overrides_rename_on_attach_root_step_without_continuation_stays_done() -> (
    None
):
    """An answered root step stays DONE until work is handed off."""
    root, root_step = _rename_on_attach_root_step(
        question_response_path="/tmp/question-response.json"
    )

    _apply_status_overrides([root], [root_step])

    assert root_step.status == "DONE"


def test_apply_status_overrides_plan_chain_root_step_projection_unchanged() -> None:
    """Plan-chain root steps retain their planner projection."""
    question_time = datetime(2026, 7, 29, 6, 27, 18, 856220)
    plan_time = datetime(2026, 7, 29, 6, 29, 30)
    root_start = datetime(2026, 7, 29, 6, 22, 53)
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix="20260729062253",
        role_suffix="--plan",
        agent_name="nr--plan",
        agent_family="nr",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[question_time],
        question_response_path="/tmp/question-response.json",
        plan_times=[plan_time],
        plan_action="tale",
    )
    root_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=datetime(2026, 7, 29, 6, 23, 20),
        raw_suffix=root.raw_suffix,
        parent_workflow="ace-run",
        parent_timestamp=root.raw_suffix,
        step_name="main",
        step_type="agent",
        parent_step_index=None,
        role_suffix="--plan",
        agent_name="nr--plan",
        agent_family="nr",
        agent_family_role="plan",
        questions_times=[question_time],
        question_response_path="/tmp/question-response.json",
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 29, 6, 30, 58),
        run_start_time=datetime(2026, 7, 29, 6, 30, 58),
        raw_suffix="20260729063058",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name="nr--code",
        agent_family="nr",
        agent_family_role="code",
        plan_times=[plan_time],
        plan_action="tale",
    )

    _apply_status_overrides([root, continuation], [root_step])

    assert root_step.status == "TALE APPROVED"
    assert continuation.status == "WORKING TALE"
    assert root.status == "WORKING TALE"


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


@pytest.mark.parametrize(
    ("plan_action", "expected_status"),
    [("tale", "TALE APPROVED"), ("approve", "PLAN APPROVED")],
)
def test_apply_status_overrides_question_continuation_inner_approver_runtime(
    plan_action: str,
    expected_status: str,
) -> None:
    """The visible continuation row aggregates its inner main step runtime."""
    question_time = datetime(2026, 6, 23, 7, 5, 49)
    continuation_start = datetime(2026, 6, 23, 7, 5, 50)
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
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=continuation_start,
        run_start_time=continuation_start,
        raw_suffix="20260623070550",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="q",
        questions_times=[question_time],
        plan_times=[plan_time],
        plan_action=plan_action,
    )
    inner_main_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=continuation_start,
        run_start_time=continuation_start,
        raw_suffix=continuation.raw_suffix,
        parent_workflow="ace-run",
        parent_timestamp=continuation.raw_suffix,
        step_type="agent",
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="q",
        questions_times=[question_time],
        plan_times=[plan_time],
        plan_action=plan_action,
    )
    continuation.runtime_children.append(inner_main_step)

    _apply_status_overrides([parent, continuation], [inner_main_step])

    assert continuation.status == expected_status
    assert inner_main_step.status == expected_status
    assert compute_row_runtime(continuation, now=datetime(2026, 6, 23, 7, 33, 38)) == (
        ("", "07:06:42"),
        "52s",
    )
    assert runtime_suffix_ticks(continuation) is False


def test_apply_status_overrides_question_continuation_asker_runtime_freezes() -> None:
    """A handed-off ANSWERED asker freezes at the answer time, not family end."""
    root_start = datetime(2026, 6, 23, 8, 48, 1)
    question_time = datetime(2026, 6, 23, 8, 57, 58)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix="20260623084801",
        role_suffix="--0",
        agent_name="sase-046",
        agent_family="sase-046",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[question_time],
    )
    asker = Agent(
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
        agent_name="sase-046--0",
        agent_family="sase-046",
        agent_family_role="q",
    )
    continuation_planner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 8, 57, 59),
        run_start_time=datetime(2026, 6, 23, 8, 57, 59),
        raw_suffix="20260623085759",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--plan",
        agent_name="sase-046--1",
        agent_family="sase-046",
        agent_family_role="q",
        questions_times=[question_time],
        plan_times=[datetime(2026, 6, 23, 9, 18, 11)],
        plan_action="tale",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 6, 23, 9, 18, 20),
        run_start_time=datetime(2026, 6, 23, 9, 18, 20),
        raw_suffix="20260623091820",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--code",
        agent_name="sase-046--code",
        agent_family="sase-046",
        agent_family_role="code",
    )

    _apply_status_overrides([parent, continuation_planner, coder], [asker])

    assert asker.status == "ANSWERED"
    assert asker.stop_time == question_time
    assert compute_row_runtime(asker, now=datetime(2026, 6, 23, 9, 42, 27)) == (
        ("", "08:57:58"),
        "9m57s",
    )
    assert runtime_suffix_ticks(asker) is False


def test_apply_status_overrides_answered_without_followup_keeps_runtime_live() -> None:
    """A single live ANSWERED row is not pinned without a continuation handoff."""
    root_start = datetime(2026, 6, 23, 8, 48, 1)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="ANSWERED",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix="20260623084801",
        role_suffix="--0",
        agent_name="sase-live",
        agent_family="sase-live",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[datetime(2026, 6, 23, 8, 57, 58)],
    )
    asker = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=root_start,
        run_start_time=root_start,
        raw_suffix=parent.raw_suffix,
        parent_workflow="ace-run",
        parent_timestamp=parent.raw_suffix,
        step_type="agent",
        role_suffix="--0",
        agent_name="sase-live--0",
        agent_family="sase-live",
        agent_family_role="q",
    )

    _apply_status_overrides([parent], [asker])

    assert asker.status == "ANSWERED"
    assert asker.stop_time is None
    assert compute_row_runtime(asker, now=datetime(2026, 6, 23, 9, 3, 1)) == (
        None,
        "15m",
    )
    assert runtime_suffix_ticks(asker) is True

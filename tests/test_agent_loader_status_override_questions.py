"""Tests for _apply_status_overrides question status decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_done_with_unanswered_question_without_gate_stays_done() -> (
    None
):
    """A legacy completed row no longer reconstructs QUESTION from timestamps."""
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

    assert agent.status == "DONE"


def test_apply_status_overrides_done_with_answered_question_stays_done() -> None:
    """A DONE agent with a follow-up stays DONE (question was answered)."""
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
        role_suffix="--1",
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
    """An answered question-only family shows DONE with an ANSWERED asker row."""
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
        agent_family_role="agent",
        questions_times=[question_time],
    )
    agents = [parent, continuation]

    _apply_status_overrides(agents)

    assert continuation.status == "DONE"
    assert parent.status == "DONE"


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
        agent_family_role="agent",
    )

    _apply_status_overrides([root, continuation], [root_step])

    assert root_step.status == "ANSWERED"
    assert root_step.stop_time == max(root_step.questions_times)
    assert root.status == "RUNNING"
    assert continuation.status == "RUNNING"


def test_apply_status_overrides_rename_on_attach_root_step_without_gate_stays_done() -> (
    None
):
    """A legacy unanswered root step no longer reconstructs QUESTION."""
    root, root_step = _rename_on_attach_root_step(question_response_path=None)

    _apply_status_overrides([root], [root_step])

    assert root_step.status == "DONE"


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
    """A plan-chain root's own concrete step keeps its raw DONE status.

    The sticky-approved mirror used to come from the retired synthetic planner
    path; the gate shell now owns the
    container's and follow-up code child's approved labels instead.
    """
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

    assert root_step.status == "DONE"
    assert continuation.status == "WORKING TALE"
    assert root.status == "WORKING TALE"

"""Tests for follow-up root and workflow-row status overrides."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def _plain_root(
    *,
    status: str,
    start: datetime = datetime(2026, 5, 17, 9, 0, 0),
    raw_suffix: str = "20260517090000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="root",
        project_file="/tmp/test.sase",
        status=status,
        start_time=start,
        run_start_time=start if status == "RUNNING" else None,
        raw_suffix=raw_suffix,
    )


def _family_child(
    *,
    status: str,
    start: datetime,
    parent: Agent,
    raw_suffix: str,
    cl_name: str,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=start,
        run_start_time=start if status == "RUNNING" else None,
        raw_suffix=raw_suffix,
        parent_timestamp=parent.raw_suffix,
    )


def test_apply_status_overrides_plain_root_mirrors_waiting_child() -> None:
    parent = _plain_root(status="DONE")
    child = _family_child(
        status="WAITING",
        start=datetime(2026, 5, 17, 9, 5, 0),
        parent=parent,
        raw_suffix="20260517090500",
        cl_name="launch",
    )
    child.waiting_for = ["dep"]
    child.wait_duration = 300

    _apply_status_overrides([parent, child])

    assert parent.status == "WAITING"
    assert parent.wait_display_source is child


def test_apply_status_overrides_running_child_beats_waiting_child() -> None:
    parent = _plain_root(status="DONE")
    running = _family_child(
        status="RUNNING",
        start=datetime(2026, 5, 17, 9, 5, 0),
        parent=parent,
        raw_suffix="20260517090500",
        cl_name="running",
    )
    waiting = _family_child(
        status="WAITING",
        start=datetime(2026, 5, 17, 9, 10, 0),
        parent=parent,
        raw_suffix="20260517091000",
        cl_name="waiting",
    )

    _apply_status_overrides([parent, running, waiting])

    assert parent.status == "RUNNING"
    assert parent.wait_display_source is None


def test_apply_status_overrides_two_active_children_newest_wins() -> None:
    parent = _plain_root(status="DONE")
    older = _family_child(
        status="RUNNING",
        start=datetime(2026, 5, 17, 9, 5, 0),
        parent=parent,
        raw_suffix="20260517090500",
        cl_name="older",
    )
    newer = _family_child(
        status="RETRYING",
        start=datetime(2026, 5, 17, 9, 10, 0),
        parent=parent,
        raw_suffix="20260517091000",
        cl_name="newer",
    )

    _apply_status_overrides([parent, older, newer])

    assert parent.status == "RETRYING"


def test_apply_status_overrides_two_waiting_children_oldest_wins() -> None:
    parent = _plain_root(status="DONE")
    older = _family_child(
        status="WAITING",
        start=datetime(2026, 5, 17, 9, 5, 0),
        parent=parent,
        raw_suffix="20260517090500",
        cl_name="older",
    )
    newer = _family_child(
        status="WAITING",
        start=datetime(2026, 5, 17, 9, 10, 0),
        parent=parent,
        raw_suffix="20260517091000",
        cl_name="newer",
    )

    _apply_status_overrides([parent, older, newer])

    assert parent.status == "WAITING"
    assert parent.wait_display_source is older


def test_apply_status_overrides_plain_running_root_beats_waiting_child() -> None:
    parent = _plain_root(status="RUNNING")
    waiting = _family_child(
        status="WAITING",
        start=datetime(2026, 5, 17, 9, 5, 0),
        parent=parent,
        raw_suffix="20260517090500",
        cl_name="waiting",
    )

    _apply_status_overrides([parent, waiting])

    assert parent.status == "RUNNING"
    assert parent.wait_display_source is None


def test_apply_status_overrides_plain_root_keeps_terminal_status_without_activity() -> (
    None
):
    parent = _plain_root(status="DONE")
    child = _family_child(
        status="DONE",
        start=datetime(2026, 5, 17, 9, 5, 0),
        parent=parent,
        raw_suffix="20260517090500",
        cl_name="done",
    )

    _apply_status_overrides([parent, child])

    assert parent.status == "DONE"
    assert parent.wait_display_source is None


def test_apply_status_overrides_sticky_approved_planner_is_not_active() -> None:
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="agent-family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="-plan",
        agent_family="ap5",
        agent_family_role="root",
        plan_chain_root=True,
    )
    planner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="planner",
        project_file="/tmp/test.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 5, 17, 9, 0, 0),
        raw_suffix="20260517090000",
        parent_timestamp=parent.raw_suffix,
        role_suffix="-plan",
        agent_family="ap5",
        agent_family_role="plan",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="coder",
        project_file="/tmp/test.sase",
        status="PLAN DONE",
        start_time=datetime(2026, 5, 17, 9, 10, 0),
        raw_suffix="20260517091000",
        parent_timestamp=parent.raw_suffix,
        role_suffix="-code",
        agent_family="ap5",
        agent_family_role="code",
    )

    _apply_status_overrides([parent, planner, coder])

    assert parent.status == "PLAN DONE"


def test_apply_status_overrides_root_awaiting_plan_review_mirrors_planner() -> None:
    """A family root mirrors the logical planner child while awaiting review."""
    plan_time = datetime(2026, 5, 17, 9, 0, 0)
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
        plan_times=[plan_time],
    )
    agents = [parent]

    _apply_status_overrides(agents)

    assert parent.status == "PLAN"
    planner = next(a for a in agents if a.parent_timestamp == parent.raw_suffix)
    assert planner.agent_name == "root--plan"
    assert planner.status == "PLAN"


def test_apply_status_overrides_question_root_synthesizes_zero_child() -> None:
    """A first-agent question root synthesizes the logical '--0' child."""
    question_time = datetime(2026, 5, 17, 9, 0, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="--0",
        agent_name="root",
        agent_family="root",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[question_time],
    )
    agents = [parent]

    _apply_status_overrides(agents)

    assert parent.status == "QUESTION"
    question_child = next(a for a in agents if a.parent_timestamp == parent.raw_suffix)
    assert question_child.agent_name == "root--0"
    assert question_child.agent_family_role is None
    assert question_child.role_suffix == "--0"
    assert question_child.status == "QUESTION"


def test_apply_status_overrides_ap5_workflow_children_after_code_handoff() -> None:
    """The planner step is sticky-approved; embedded workflow children stay terminal."""
    plan_time = datetime(2026, 5, 17, 9, 0, 0)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="agent-family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        role_suffix="-plan",
        agent_name="ap5",
        agent_family="ap5",
        agent_family_role="root",
        plan_chain_root=True,
        plan_times=[plan_time],
    )
    planner_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        parent_workflow="agent-family",
        parent_timestamp="20260517085500",
        step_type="agent",
        step_index=0,
        total_steps=3,
        role_suffix="-plan",
        agent_name="ap5-plan",
        agent_family="ap5",
        agent_family_role="plan",
    )
    bash_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="resolve",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 8, 55, 0),
        raw_suffix="20260517085500",
        parent_workflow="agent-family",
        parent_timestamp="20260517085500",
        step_type="bash",
        step_index=1,
        total_steps=3,
        role_suffix="-plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="code",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 17, 9, 10, 0),
        raw_suffix="20260517091000",
        parent_timestamp="20260517085500",
        role_suffix="-code",
        agent_name="ap5-code",
        agent_family="ap5",
        agent_family_role="code",
    )
    agents = [parent, code_child]
    workflow_steps = [planner_step, bash_step]

    _apply_status_overrides(agents, workflow_steps)

    assert planner_step.status == "PLAN APPROVED"
    assert bash_step.status == "DONE"
    assert code_child.status == "PLAN DONE"
    assert parent.status == "PLAN DONE"

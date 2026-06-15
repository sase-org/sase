"""Tests for _apply_status_overrides follow-up child status decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


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


def test_apply_status_overrides_root_question_synthesizes_zero_child() -> None:
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
    assert question_child.agent_family_role == "q"
    assert question_child.role_suffix == "--0"
    assert question_child.status == "QUESTION"


def test_apply_status_overrides_ap5_workflow_children_after_code_handoff() -> None:
    """Planner and embedded workflow children stay terminal after family handoff."""
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

    assert planner_step.status == "DONE"
    assert bash_step.status == "DONE"
    assert code_child.status == "PLAN DONE"
    assert parent.status == "PLAN DONE"


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


def test_apply_status_overrides_feedback_child_approved_by_metadata_stays_done() -> (
    None
):
    """A feedback child with approved-plan metadata is no longer awaiting review."""
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

    assert feedback_child.status == "DONE"
    assert parent.status == "DONE"


def test_apply_status_overrides_feedback_child_after_code_handoff_stays_done() -> None:
    """A feedback child followed by active code is a completed handoff step."""
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

    assert feedback_child.status == "DONE"
    assert code_child.status == "TALE APPROVED"
    assert parent.status == "TALE APPROVED"


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


def test_apply_status_overrides_done_with_active_code_followup_becomes_plan_approved() -> (
    None
):
    """A DONE .plan parent with a completed feedback child + active .code child is PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
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
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 17, 16, 50, 0),
        parent_timestamp="20260417163326",
        role_suffix=".code",
    )
    agents = [parent, feedback_child, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"
    assert code_child.status == "PLAN APPROVED"


def test_apply_status_overrides_completed_followup_plan_child_stays_done() -> None:
    """A completed follow-up planner child is not relabeled as PLAN."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 25, 10, 0, 0),
        raw_suffix="20260425100000",
        role_suffix=".plan",
    )
    followup_planner = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 25, 10, 5, 0),
        raw_suffix="20260425100500",
        parent_timestamp="20260425100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 10, 10, 0),
        parent_timestamp="20260425100000",
        role_suffix=".code",
    )
    agents = [parent, followup_planner, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"
    assert followup_planner.status == "DONE"
    assert code_child.status == "PLAN APPROVED"


def test_apply_status_overrides_active_epic_child_sets_epic_approved() -> None:
    """A DONE plan parent with an active .epic follow-up becomes EPIC APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "RUNNING"


def test_apply_status_overrides_active_commit_child_sets_plan_committed() -> None:
    """A DONE plan parent with an active .commit follow-up becomes PLAN COMMITTED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    commit_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".commit",
    )
    agents = [parent, commit_child]
    _apply_status_overrides(agents)

    assert parent.status == "RUNNING"


def test_apply_status_overrides_active_code_child_stays_plan_approved() -> None:
    """A DONE plan parent with an active .code follow-up stays PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"
    assert code_child.status == "PLAN APPROVED"


def test_apply_status_overrides_active_code_question_child_stays_plan_approved() -> (
    None
):
    """An active '--code-0' continuation is still a code handoff row."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix="--code-0",
        agent_family_role="code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"
    assert code_child.status == "PLAN APPROVED"


def test_apply_status_overrides_completed_epic_child_sets_epic_created() -> None:
    """A DONE plan parent whose only completed follow-up is `.epic` becomes EPIC CREATED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "EPIC CREATED"
    assert epic_child.status == "EPIC CREATED"


def test_apply_status_overrides_failed_epic_child_stays_plan_done() -> None:
    """A FAILED .epic child means the bead was not created - parent stays PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "FAILED"


def test_apply_status_overrides_epic_then_code_completed_latest_wins() -> None:
    """A `.code` child completed after a `.epic` child falls back to PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 20, 0),
        parent_timestamp="20260420100000",
        role_suffix=".code",
    )
    agents = [parent, epic_child, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN DONE"
    assert code_child.status == "PLAN DONE"


def test_apply_status_overrides_epic_and_code_active_newest_wins() -> None:
    """With both an active .epic and .code child, the most-recently-started wins."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".code",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 20, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, code_child, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "RUNNING"

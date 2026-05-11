"""Tests for _apply_status_overrides follow-up status decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_plan_rejected_stays_terminal() -> None:
    """A rejected plan is terminal, not another plan awaiting approval."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="PLAN REJECTED",
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

    assert parent.status == "PLAN REJECTED"


def test_apply_status_overrides_done_with_active_code_followup_becomes_plan_approved() -> (
    None
):
    """A DONE .plan parent with a completed feedback child + active .code child is PLAN APPROVED."""
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
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 17, 16, 50, 0),
        parent_timestamp="20260417163326",
        role_suffix=".code",
    )
    agents = [parent, feedback_child, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"


def test_apply_status_overrides_completed_followup_plan_child_stays_done() -> None:
    """A completed follow-up planner child is not relabeled as PLANNING."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 25, 10, 0, 0),
        raw_suffix="20260425100000",
        role_suffix=".plan",
    )
    followup_planner = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 25, 10, 5, 0),
        raw_suffix="20260425100500",
        parent_timestamp="20260425100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 10, 10, 0),
        parent_timestamp="20260425100000",
        role_suffix=".code",
    )
    agents = [parent, followup_planner, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"
    assert followup_planner.status == "DONE"


def test_apply_status_overrides_active_epic_child_sets_epic_approved() -> None:
    """A DONE plan parent with an active .epic follow-up becomes EPIC APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "EPIC APPROVED"


def test_apply_status_overrides_active_commit_child_sets_plan_committed() -> None:
    """A DONE plan parent with an active .commit follow-up becomes PLAN COMMITTED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    commit_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".commit",
    )
    agents = [parent, commit_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN COMMITTED"


def test_apply_status_overrides_active_code_child_stays_plan_approved() -> None:
    """A DONE plan parent with an active .code follow-up stays PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"


def test_apply_status_overrides_completed_epic_child_sets_epic_created() -> None:
    """A DONE plan parent whose only completed follow-up is `.epic` becomes EPIC CREATED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "EPIC CREATED"


def test_apply_status_overrides_failed_epic_child_stays_plan_done() -> None:
    """A FAILED .epic child means the bead was not created - parent stays PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="FAILED",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN DONE"


def test_apply_status_overrides_epic_then_code_completed_latest_wins() -> None:
    """A `.code` child completed after a `.epic` child falls back to PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 20, 0),
        parent_timestamp="20260420100000",
        role_suffix=".code",
    )
    agents = [parent, epic_child, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN DONE"


def test_apply_status_overrides_epic_and_code_active_newest_wins() -> None:
    """With both an active .epic and .code child, the most-recently-started wins."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 20, 10, 0, 0),
        raw_suffix="20260420100000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 10, 0),
        parent_timestamp="20260420100000",
        role_suffix=".code",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 20, 10, 20, 0),
        parent_timestamp="20260420100000",
        role_suffix=".epic",
    )
    agents = [parent, code_child, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "EPIC APPROVED"


def test_apply_status_overrides_done_with_unanswered_question_becomes_question() -> (
    None
):
    """A DONE agent with questions_times and no .q follow-up becomes QUESTION."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
        questions_times=[datetime(2026, 4, 21, 16, 17, 4)],
    )
    q_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 40, 0),
        parent_timestamp="20260511091000",
        role_suffix=".q",
    )
    agents = [parent, code_child, q_grandchild]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN DONE"


def test_apply_status_overrides_parent_with_active_code_after_question_is_plan_approved() -> (
    None
):
    """An active .code child (answer in flight) keeps the parent at PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        raw_suffix="20260511091000",
        parent_timestamp="20260511090000",
        role_suffix=".code",
        questions_times=[datetime(2026, 5, 11, 9, 30, 0)],
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"


def test_apply_status_overrides_active_code_child_with_tale_plan_action_is_tale_approved() -> (
    None
):
    """A DONE plan parent with plan_action=tale and an active .code child becomes TALE APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE APPROVED"


def test_apply_status_overrides_active_code_child_without_plan_action_is_plan_approved() -> (
    None
):
    """Regression guard: a generic-approve parent (no plan_action) stays PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action=None,
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"


def test_apply_status_overrides_active_code_child_with_parent_status_tale_approved() -> (
    None
):
    """In-session-mask path: parent.status starts as TALE APPROVED, no plan_action."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="TALE APPROVED",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE APPROVED"


def test_apply_status_overrides_questioning_code_with_tale_plan_action_still_becomes_question() -> (
    None
):
    """A parent with plan_action=tale whose .code child has an unanswered question still becomes QUESTION."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
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


def test_apply_status_overrides_done_with_tale_plan_action_yields_tale_done() -> None:
    """A DONE .plan parent with plan_action=tale and a completed .code child becomes TALE DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE DONE"


def test_apply_status_overrides_done_tale_with_completed_epic_followup_still_yields_epic_created() -> (
    None
):
    """An .epic follow-up wins over the tale-vs-plan branch when it was the newest to complete."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "EPIC CREATED"


def test_apply_status_overrides_done_without_tale_plan_action_still_yields_plan_done() -> (
    None
):
    """Regression guard: a generic-approve parent (no plan_action) still becomes PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action=None,
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN DONE"


def test_apply_status_overrides_done_without_questions_stays_done() -> None:
    """A DONE agent with empty questions_times stays DONE."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
    )
    agents = [agent]
    _apply_status_overrides(agents)

    assert agent.status == "DONE"

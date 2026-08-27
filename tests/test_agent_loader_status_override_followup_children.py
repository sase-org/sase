"""Tests for concrete follow-up child role status overrides."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_done_with_active_code_followup_becomes_working_plan() -> (
    None
):
    """A DONE .plan parent with a completed feedback child + active .code child is WORKING PLAN."""
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

    assert parent.status == "WORKING PLAN"
    assert code_child.status == "WORKING PLAN"


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

    assert parent.status == "WORKING PLAN"
    assert followup_planner.status == "DONE"
    assert code_child.status == "WORKING PLAN"


def test_apply_status_overrides_propagates_plan_metadata_to_family_children() -> None:
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 4, 25, 10, 0, 0),
        raw_suffix="20260425100000",
        role_suffix="--plan",
        plan_path="sase/repos/plans/202607/plan.md",
        archived_plan_path="/home/user/.sase/plans/202607/plan.md",
        sdd_plan_path="sase/repos/plans/202607/plan.md",
        plan_committed=True,
        plan_action="tale",
        epic_bead_id="sase-1",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 10, 5, 0),
        parent_timestamp="20260425100000",
        role_suffix="--code",
    )

    _apply_status_overrides([parent, child])

    assert child.plan_path == parent.plan_path
    assert child.archived_plan_path == parent.archived_plan_path
    assert child.sdd_plan_path == parent.sdd_plan_path
    assert child.plan_committed is True
    assert child.plan_action == "tale"
    assert child.epic_bead_id == "sase-1"


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

    assert parent.status == "EPIC APPROVED"
    assert epic_child.status == "EPIC APPROVED"


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

    assert parent.status == "PLAN COMMITTED"
    assert commit_child.status == "PLAN COMMITTED"


def test_apply_status_overrides_active_code_child_sets_working_plan() -> None:
    """A DONE plan parent with an active .code follow-up mirrors WORKING PLAN."""
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

    assert parent.status == "WORKING PLAN"
    assert code_child.status == "WORKING PLAN"


def test_apply_status_overrides_active_code_child_continuation_sets_working_plan() -> (
    None
):
    """An active code continuation remains a code handoff row."""
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
        role_suffix="--1",
        agent_family_role="code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "WORKING PLAN"
    assert code_child.status == "WORKING PLAN"


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

    assert parent.status == "EPIC APPROVED"
    assert epic_child.status == "EPIC APPROVED"

"""Tests for _apply_status_overrides plan-entry status decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def _agent(
    *,
    status: str = "DONE",
    start_time: datetime | None = None,
    raw_suffix: str | None = None,
    parent_timestamp: str | None = None,
    role_suffix: str | None = None,
    agent_type: AgentType = AgentType.RUNNING,
    plan_times: list[datetime] | None = None,
    feedback_times: list[datetime] | None = None,
    plan_action: str | None = None,
    agent_name: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    plan_chain_root: bool = False,
    plan_path: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status=status,
        start_time=start_time,
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
        role_suffix=role_suffix,
        plan_times=plan_times or [],
        feedback_times=feedback_times or [],
        plan_action=plan_action,
        agent_name=agent_name,
        agent_family=agent_family,
        agent_family_role=agent_family_role,
        plan_chain_root=plan_chain_root,
        plan_path=plan_path,
    )


def test_apply_status_overrides_done_planner_entry_without_gate_stays_done() -> None:
    """A legacy completed planner entry no longer reconstructs pending PLAN."""
    planner = _agent(
        start_time=datetime(2026, 5, 29, 9, 30, 0),
        raw_suffix="20260529093000",
        parent_timestamp="20260529090000",
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 9, 35, 0)],
    )

    _apply_status_overrides([planner])

    assert planner.status == "DONE"


def test_apply_status_overrides_family_root_without_gate_mirrors_done_planner() -> None:
    """A legacy plan-chain root without a gate degrades to DONE."""
    root_timestamp = "20260529090000"
    root = _agent(
        agent_type=AgentType.WORKFLOW,
        start_time=datetime(2026, 5, 29, 9, 0, 0),
        raw_suffix=root_timestamp,
        role_suffix="--0",
        agent_name="bph.cld",
        agent_family="bph.cld",
        agent_family_role="root",
        plan_chain_root=True,
    )
    planner = _agent(
        start_time=datetime(2026, 5, 29, 9, 30, 0),
        raw_suffix="20260529093000",
        parent_timestamp=root_timestamp,
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 9, 35, 0)],
        agent_name="bph.cld-2",
        agent_family="bph.cld",
        agent_family_role="plan",
    )

    _apply_status_overrides([root, planner])

    assert planner.status == "DONE"
    assert root.status == "DONE"


def test_apply_status_overrides_approved_tale_is_not_reopened_as_plan() -> None:
    """A tale-approved plan with completed code remains a terminal tale handoff."""
    root_timestamp = "20260529100000"
    parent = _agent(
        agent_type=AgentType.WORKFLOW,
        start_time=datetime(2026, 5, 29, 10, 0, 0),
        raw_suffix=root_timestamp,
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 10, 5, 0)],
        plan_action="tale",
        agent_name="bph.cld",
        agent_family="bph.cld",
        agent_family_role="root",
        plan_chain_root=True,
    )
    code_child = _agent(
        start_time=datetime(2026, 5, 29, 10, 20, 0),
        raw_suffix="20260529102000",
        parent_timestamp=root_timestamp,
        role_suffix="-code",
        agent_name="bph.cld-code",
        agent_family="bph.cld",
        agent_family_role="code",
    )

    _apply_status_overrides([parent, code_child])

    assert parent.status == "TALE DONE"
    assert code_child.status == "TALE DONE"


def test_apply_status_overrides_unreviewed_plan_entry_done_is_idempotent() -> None:
    """Reapplying overrides leaves legacy pending-review timestamps terminal."""
    planner = _agent(
        start_time=datetime(2026, 5, 29, 12, 0, 0),
        raw_suffix="20260529120000",
        parent_timestamp="20260529113000",
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 12, 5, 0)],
    )
    agents = [planner]

    _apply_status_overrides(agents)
    _apply_status_overrides(agents)

    assert planner.status == "DONE"

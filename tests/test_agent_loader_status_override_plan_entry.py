"""Tests for _apply_status_overrides plan-entry status decisions."""

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.models import _agent_status_overrides as status_overrides
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
    workspace_dir: str | None = None,
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
        workspace_dir=workspace_dir,
    )


def test_apply_status_overrides_done_planner_entry_awaiting_review_becomes_plan() -> (
    None
):
    """A completed planner entry with an unreviewed plan is still in PLAN."""
    planner = _agent(
        start_time=datetime(2026, 5, 29, 9, 30, 0),
        raw_suffix="20260529093000",
        parent_timestamp="20260529090000",
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 9, 35, 0)],
    )

    _apply_status_overrides([planner])

    assert planner.status == "PLAN"


@pytest.mark.parametrize(("tier", "expected"), [("tale", "TALE"), ("epic", "EPIC")])
def test_apply_status_overrides_uses_pending_plan_tier(
    tmp_path: Path,
    tier: str,
    expected: str,
) -> None:
    plan_path = tmp_path / f"{tier}.md"
    plan_path.write_text(f"---\ntier: {tier}\n---\n# Plan\n", encoding="utf-8")
    planner = _agent(
        start_time=datetime(2026, 5, 29, 9, 30, 0),
        raw_suffix="20260529093000",
        parent_timestamp="20260529090000",
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 9, 35, 0)],
        plan_path=str(plan_path),
    )

    _apply_status_overrides([planner])

    assert planner.status == expected


def test_apply_status_overrides_resolves_relative_plan_from_agent_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    plan_path = workspace / "plans" / "epic.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\ntier: epic\n---\n# Plan\n", encoding="utf-8")
    planner = _agent(
        start_time=datetime(2026, 5, 29, 9, 30, 0),
        raw_suffix="20260529093000",
        parent_timestamp="20260529090000",
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 9, 35, 0)],
        plan_path="plans/epic.md",
        workspace_dir=str(workspace),
    )

    _apply_status_overrides([planner])

    assert planner.status == "EPIC"


def test_apply_status_overrides_family_root_mirrors_plan_entry() -> None:
    """A plan-chain root mirrors a child planner entry awaiting review."""
    root_timestamp = "20260529090000"
    root = _agent(
        agent_type=AgentType.WORKFLOW,
        start_time=datetime(2026, 5, 29, 9, 0, 0),
        raw_suffix=root_timestamp,
        role_suffix="-q",
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

    assert planner.status == "PLAN"
    assert root.status == "PLAN"


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


def test_apply_status_overrides_superseded_planner_entry_stays_done() -> None:
    """A newer sibling round proves the prior planner entry is no longer pending."""
    root_timestamp = "20260529110000"
    planner = _agent(
        start_time=datetime(2026, 5, 29, 11, 0, 0),
        raw_suffix="20260529110030",
        parent_timestamp=root_timestamp,
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 11, 5, 0)],
    )
    feedback = _agent(
        start_time=datetime(2026, 5, 29, 11, 15, 0),
        raw_suffix="20260529111500",
        parent_timestamp=root_timestamp,
        role_suffix="-2",
    )

    _apply_status_overrides([planner, feedback])

    assert planner.status == "DONE"


def test_feedback_review_progression_uses_precomputed_child_latest() -> None:
    """The hot review check can answer from the parent child index."""
    root_timestamp = "20260529113000"
    planner = _agent(
        start_time=datetime(2026, 5, 29, 11, 30, 0),
        raw_suffix="20260529113030",
        parent_timestamp=root_timestamp,
        role_suffix="-plan",
        plan_times=[datetime(2026, 5, 29, 11, 35, 0)],
    )
    newer_feedback = _agent(
        start_time=datetime(2026, 5, 29, 11, 45, 0),
        raw_suffix="20260529114500",
        parent_timestamp=root_timestamp,
        role_suffix="-2",
    )
    all_agents = [planner, newer_feedback]
    children_by_parent = status_overrides._children_by_parent_timestamp(all_agents)
    latest_by_parent = status_overrides._latest_non_workflow_child_launch_by_parent(
        children_by_parent
    )

    class ExplodingAgents(list[Agent]):
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("should not scan all_agents")

    assert status_overrides._feedback_child_progressed_past_review(
        planner,
        ExplodingAgents(all_agents),
        children_by_parent,
        latest_by_parent,
    )


def test_apply_status_overrides_unreviewed_plan_entry_is_idempotent() -> None:
    """Reapplying overrides keeps a pending planner entry in PLAN."""
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

    assert planner.status == "PLAN"

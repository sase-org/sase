"""Concrete-agent status counter projection tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_clan import agent_summary_status_counts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType

_STARTED = datetime(2026, 7, 19, 9, 0, 0)


def _agent(
    name: str,
    status: str,
    *,
    role: str,
    parent_timestamp: str | None = None,
    clan: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/family.sase",
        status=status,
        start_time=_STARTED,
        raw_suffix=f"suffix-{name}",
        parent_timestamp=parent_timestamp,
        agent_name=name,
        agent_family="alpha",
        agent_family_role="root" if role == "plan" else role,
        role_suffix=f"--{role}",
        plan_chain_root=role == "plan",
        agent_clan=clan,
        agent_clan_generation="gen-1" if clan else None,
    )


def _active_family(*, clan: str | None = None) -> tuple[Agent, Agent]:
    planner = _agent("alpha--plan", "TALE APPROVED", role="plan", clan=clan)
    coder = _agent(
        "alpha--code",
        "WORKING TALE",
        role="code",
        parent_timestamp=planner.raw_suffix,
        clan=clan,
    )
    planner.followup_agents = [coder]
    planner.runtime_children = [coder]
    return planner, coder


def test_family_container_projects_members_and_settled_statuses() -> None:
    planner, _coder = _active_family()

    counts = agent_summary_status_counts((planner,), ())

    assert counts.total == 2
    assert counts.running == 1
    assert counts.done == 1


def test_planner_only_approved_family_stays_running() -> None:
    planner = _agent("alpha--plan", "PLAN APPROVED", role="plan")

    counts = agent_summary_status_counts((planner,), ())

    assert counts.total == 1
    assert counts.running == 1
    assert counts.done == 0


def test_clan_projection_recurses_into_sequential_family() -> None:
    planner, coder = _active_family(clan="research")
    container = project_clan_tree([planner, coder])[0]

    counts = agent_summary_status_counts((container,), ())

    assert counts.total == 2
    assert counts.running == 1
    assert counts.done == 1


def test_container_unread_is_attributed_once_to_projected_member() -> None:
    root, coder = _active_family()
    planner = _agent(
        "alpha--plan-step",
        "TALE APPROVED",
        role="plan-step",
        parent_timestamp=root.raw_suffix,
    )
    planner.parent_workflow = "ace-run"
    planner.step_type = "agent"
    root.runtime_children = [planner, coder]

    container_only = agent_summary_status_counts((root,), {root.identity})
    container_and_member = agent_summary_status_counts(
        (root,),
        {root.identity, planner.identity},
    )

    assert container_only.total == 2
    assert container_only.unread == 1
    assert container_only.done == 1
    assert container_and_member.unread == 1
    assert container_and_member.done == 0

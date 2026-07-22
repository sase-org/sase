"""Concrete-agent status counter projection tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_clan import (
    agent_hole_count,
    agent_summary_status_counts,
)
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
    parallel: bool = False,
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
        agent_family_parallel=parallel,
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


def test_agent_holes_count_each_standalone_agent() -> None:
    agents = (
        _agent("alpha", "RUNNING", role="solo"),
        _agent("beta", "DONE", role="solo"),
    )

    assert agent_hole_count(agents) == 2


def test_agent_holes_keep_sequential_family_as_one_hole() -> None:
    planner, _coder = _active_family()

    assert agent_hole_count((planner,)) == 1
    assert agent_summary_status_counts((planner,), ()).total == 2


def test_agent_holes_count_clan_direct_members_without_family_descendants() -> None:
    planner, coder = _active_family(clan="research")
    standalone = _agent("research-audit", "WAITING", role="solo", clan="research")
    container = project_clan_tree([planner, coder, standalone])[0]

    assert agent_hole_count((container,)) == 2
    assert agent_summary_status_counts((container,), ()).total == 3


def test_agent_holes_dedupe_stable_identities_across_clans_and_panels() -> None:
    first = _agent("shared", "RUNNING", role="solo", clan="first")
    second = _agent("shared", "DONE", role="solo", clan="second")
    panel_duplicate = _agent("shared", "WAITING", role="solo")
    first_container = project_clan_tree([first])[0]
    second_container = project_clan_tree([second])[0]

    assert agent_hole_count((first_container, second_container, panel_duplicate)) == 1


def test_agent_holes_preserve_legacy_parallel_family_projection() -> None:
    root = _agent("parallel", "WAITING", role="root", parallel=True)
    members = [
        _agent(
            f"parallel-{index}",
            "RUNNING",
            role="member",
            parent_timestamp=root.raw_suffix,
            parallel=True,
        )
        for index in range(3)
    ]
    root.runtime_children.extend(members)
    unloaded = _agent("unloaded", "WAITING", role="root", parallel=True)

    assert agent_hole_count((root,)) == 3
    assert agent_summary_status_counts((root,), ()).total == 3
    assert agent_hole_count((unloaded,)) == 1


def test_agent_hole_screenshot_cardinality_is_31_for_56_concrete_agents() -> None:
    family_root = _agent("large--plan", "DONE", role="plan")
    family_members = [
        _agent(
            f"large--member-{index}",
            "DONE",
            role=f"member-{index}",
            parent_timestamp=family_root.raw_suffix,
        )
        for index in range(25)
    ]
    family_root.followup_agents.extend(family_members)
    family_root.runtime_children.extend(family_members)
    standalones = [
        _agent(f"standalone-{index}", "DONE", role="solo") for index in range(30)
    ]
    top_level = (family_root, *standalones)

    assert agent_hole_count(top_level) == 31
    assert agent_summary_status_counts(top_level, ()).total == 56


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

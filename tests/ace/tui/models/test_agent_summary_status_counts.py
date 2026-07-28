"""Concrete-agent and agent-lane status counter projection tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_clan import (
    ClanStatusCounts,
    agent_lane_status_counts,
    agent_summary_status_counts,
    clan_member_counts,
    clan_members,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context

_STARTED = datetime(2026, 7, 19, 9, 0, 0)


def _agent(
    name: str,
    status: str,
    *,
    role: str,
    parent_timestamp: str | None = None,
    clan: str | None = None,
    parallel: bool = False,
    stop_offset: int | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/family.sase",
        status=status,
        start_time=_STARTED,
        stop_time=(
            _STARTED + timedelta(minutes=stop_offset)
            if stop_offset is not None
            else None
        ),
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


def test_agent_lanes_count_each_standalone_agent() -> None:
    agents = (
        _agent("alpha", "RUNNING", role="solo"),
        _agent("beta", "DONE", role="solo"),
    )

    assert agent_lane_status_counts(agents, ()).total == 2


def test_agent_lanes_keep_sequential_family_as_one_lane() -> None:
    planner, _coder = _active_family()

    counts = agent_lane_status_counts((planner,), ())
    assert counts.total == 1
    assert counts.running == 1
    assert agent_summary_status_counts((planner,), ()).total == 2


def test_agent_lanes_count_clan_direct_members_without_family_descendants() -> None:
    planner, coder = _active_family(clan="research")
    standalone = _agent("research-audit", "WAITING", role="solo", clan="research")
    container = project_clan_tree([planner, coder, standalone])[0]

    counts = agent_lane_status_counts((container,), ())
    assert counts.total == 2
    assert counts.running == 1
    assert counts.waiting == 1
    assert agent_summary_status_counts((container,), ()).total == 3


def test_agent_lanes_dedupe_stable_identities_across_clans_and_panels() -> None:
    first = _agent("shared", "RUNNING", role="solo", clan="first")
    second = _agent("shared", "DONE", role="solo", clan="second")
    panel_duplicate = _agent("shared", "WAITING", role="solo")
    first_container = project_clan_tree([first])[0]
    second_container = project_clan_tree([second])[0]

    assert (
        agent_lane_status_counts(
            (first_container, second_container, panel_duplicate), ()
        ).total
        == 1
    )


def test_agent_lane_statuses_dedupe_terminal_owner_and_unread_state() -> None:
    read = _agent("shared", "DONE", role="solo")
    unread = _agent("shared", "DONE", role="solo", clan="second")
    container = project_clan_tree([unread])[0]

    counts = agent_lane_status_counts(
        (read, container, unread),
        {unread.identity},
    )

    assert counts.total == 1
    assert counts.unread == 1
    assert counts.done == 0


def test_agent_lanes_preserve_legacy_parallel_family_projection() -> None:
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

    loaded_counts = agent_lane_status_counts((root,), ())
    assert loaded_counts.total == 3
    assert loaded_counts.running == 3
    assert agent_summary_status_counts((root,), ()).total == 3
    unloaded_counts = agent_lane_status_counts((unloaded,), ())
    assert unloaded_counts.total == 1
    assert unloaded_counts.waiting == 1


def test_agent_lane_screenshot_cardinality_is_31_for_56_concrete_agents() -> None:
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

    lane_counts = agent_lane_status_counts(top_level, ())
    concrete_counts = agent_summary_status_counts(top_level, ())
    assert lane_counts.total == 31
    assert lane_counts.done == 31
    assert concrete_counts.total == 56
    assert concrete_counts.done == 56


def test_finished_multi_member_family_is_one_done_lane() -> None:
    root = _agent("alpha--plan", "DONE", role="plan")
    members = [
        _agent(
            f"alpha--member-{index}",
            "DONE",
            role=f"member-{index}",
            parent_timestamp=root.raw_suffix,
        )
        for index in range(3)
    ]
    root.runtime_children.extend(members)
    root.followup_agents.extend(members)

    counts = agent_lane_status_counts((root,), ())

    assert counts.total == 1
    assert counts.done == 1


def test_nested_starting_lane_rolls_up_to_running() -> None:
    member = _agent("research-starting", "STARTING", role="solo", clan="research")
    container = project_clan_tree([member])[0]

    top_level = agent_lane_status_counts((member,), ())
    nested = agent_lane_status_counts((container,), ())

    assert top_level.total == 1
    assert top_level.running == 0
    assert nested.total == 1
    assert nested.running == 1


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


def test_clan_counts_settle_handed_off_family_planner_as_done() -> None:
    family = _agent("alpha--plan", "TALE DONE", role="plan", clan="research")
    planner = _agent(
        "alpha--plan-step",
        "TALE APPROVED",
        role="plan-step",
        parent_timestamp=family.raw_suffix,
        clan="research",
    )
    planner.agent_family_role = "plan"
    planner.parent_workflow = "ace-run"
    planner.step_type = "agent"
    coder = _agent(
        "alpha--code",
        "TALE DONE",
        role="code",
        parent_timestamp=family.raw_suffix,
        clan="research",
    )
    family.runtime_children = [planner, coder]
    family.followup_agents = [coder]
    standalone = _agent(
        "research.audit",
        "RUNNING",
        role="solo",
        clan="research",
    )
    container = project_clan_tree([family, planner, coder, standalone])[0]

    assert family.is_family_container_row
    assert clan_members(container) == (family, standalone)

    clan_counts = clan_member_counts(container)
    lane_counts = agent_lane_status_counts((container,), ())

    assert clan_counts == ClanStatusCounts(running=1, done=1)
    assert (
        clan_counts.running,
        clan_counts.waiting,
        clan_counts.done,
    ) == (
        lane_counts.running,
        lane_counts.waiting,
        lane_counts.done,
    )


def test_clan_counts_settle_answered_family_planner_as_done() -> None:
    family = _agent("alpha--plan", "DONE", role="plan", clan="research")
    planner = _agent(
        "alpha--plan-step",
        "ANSWERED",
        role="plan-step",
        parent_timestamp=family.raw_suffix,
        clan="research",
        stop_offset=1,
    )
    planner.agent_family_role = "plan"
    planner.parent_workflow = "ace-run"
    planner.step_type = "agent"
    coder = _agent(
        "alpha--1",
        "DONE",
        role="code",
        parent_timestamp=family.raw_suffix,
        clan="research",
    )
    family.runtime_children = [planner, coder]
    family.followup_agents = [coder]
    standalone = _agent(
        "research.land",
        "RUNNING",
        role="solo",
        clan="research",
    )
    container = project_clan_tree([family, planner, coder, standalone])[0]

    assert clan_members(container) == (family, standalone)

    clan_counts = clan_member_counts(container)
    lane_counts = agent_lane_status_counts((container,), ())

    assert clan_counts == ClanStatusCounts(running=1, done=1)
    assert (
        clan_counts.running,
        clan_counts.waiting,
        clan_counts.done,
    ) == (
        lane_counts.running,
        lane_counts.waiting,
        lane_counts.done,
    )


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


def test_queue_counts_are_orthogonal_and_dedupe_container_flat_rows() -> None:
    implicit = _agent(
        "research.implicit",
        "WAITING",
        role="solo",
        clan="research",
    )
    explicit = _agent(
        "research.explicit",
        "WAITING",
        role="solo",
        clan="research",
    )
    dependency = _agent(
        "research.dependency",
        "WAITING",
        role="solo",
        clan="research",
    )
    for agent in (implicit, explicit, dependency):
        agent.agent_family = None
        agent.pid = 100
    implicit.wait_runners = 9
    implicit.slot_requested_at = "2026-07-19T09:00:00Z"
    explicit.wait_runners = 0
    explicit.wait_runners_explicit = True
    explicit.slot_requested_at = "2026-07-19T09:00:01Z"
    dependency.waiting_for = ["research.other"]
    refresh_runner_slot_context([implicit, explicit, dependency], effective_limit=10)
    container = project_clan_tree([implicit, explicit, dependency])[0]

    concrete = agent_summary_status_counts(
        (container, implicit, explicit, dependency),
        (),
    )
    lanes = agent_lane_status_counts(
        (container, implicit, explicit, dependency),
        (),
    )
    clan = clan_member_counts(container)

    assert (concrete.total, concrete.queued, concrete.waiting) == (3, 2, 1)
    assert (lanes.total, lanes.queued, lanes.waiting) == (3, 2, 1)
    assert (clan.queued, clan.waiting) == (2, 1)


def test_queued_waiters_partition_waiting_counts() -> None:
    members = [
        _agent(
            f"research.member-{index}",
            "WAITING",
            role="solo",
            clan="research",
        )
        for index in range(6)
    ]
    for member in members:
        member.agent_family = None
    for index, member in enumerate(members[:2]):
        member.pid = 100 + index
        member.wait_runners = 9
        member.wait_runners_explicit = index == 1
        member.slot_requested_at = f"2026-07-19T09:00:0{index}Z"
    refresh_runner_slot_context(members, effective_limit=10)
    container = project_clan_tree(members)[0]

    clan = clan_member_counts(container)
    lanes = agent_lane_status_counts((container,), ())

    assert clan == ClanStatusCounts(queued=2, waiting=4)
    assert (lanes.total, lanes.queued, lanes.waiting) == (6, 2, 4)
    assert lanes.queued + lanes.waiting == len(members)
    assert sum(
        (
            lanes.stopped,
            lanes.running,
            lanes.queued,
            lanes.waiting,
            lanes.failed,
            lanes.done,
        )
    ) == len(members)

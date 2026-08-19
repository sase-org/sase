"""Lane and monitor tallies behind Agents-tab panel border titles."""

from __future__ import annotations

from sase.ace.tui.actions.agents._display_panel_titles import agent_panel_counts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_family_members import monitor_lane_counts

from ._agent_panel_title_helpers import _agent


def _monitor_agent(name: str, *, family: str, state: str | None) -> Agent:
    settled = state not in (None, "running")
    monitor = _agent(
        name=name,
        suffix=name,
        status="MONITORED" if settled else "MONITORING",
    )
    monitor.agent_family = family
    monitor.agent_family_role = "monitor"
    monitor.role_suffix = "--mon"
    monitor.monitor_id = name
    monitor.monitor_state = state
    return monitor


def _sequential_family(
    name: str,
    *,
    tribe: str | None = None,
    clan: str | None = None,
) -> tuple[Agent, Agent]:
    root = _agent(
        name=f"{name}--plan",
        tribe=tribe,
        suffix=f"{name}-plan",
        status="TALE APPROVED",
    )
    root.agent_family = name
    root.agent_family_role = "root"
    root.role_suffix = "--plan"
    root.plan_chain_root = True
    root.agent_clan = clan
    root.agent_clan_generation = "gen-1" if clan else None
    child = _agent(
        name=f"{name}--code",
        tribe=tribe,
        suffix=f"{name}-code",
        status="WORKING TALE",
        parent_timestamp=root.raw_suffix,
    )
    child.agent_family = name
    child.agent_family_role = "code"
    child.role_suffix = "--code"
    child.agent_clan = clan
    child.agent_clan_generation = "gen-1" if clan else None
    root.followup_agents = [child]
    root.runtime_children = [child]
    return root, child


def test_panel_counts_use_lanes_for_total_and_statuses() -> None:
    standalone = _agent(
        name="standalone",
        suffix="standalone",
        status="DONE",
    )
    family_root, family_child = _sequential_family("family")
    clan_family_root, clan_family_child = _sequential_family(
        "research.family",
        clan="research",
    )
    clan_standalone = _agent(
        name="research.standalone",
        suffix="research-standalone",
        status="QUEUED",
    )
    clan_standalone.agent_clan = "research"
    clan_standalone.agent_clan_generation = "gen-1"
    clan_standalone.pid = 101
    clan_standalone.wait_runners = 9
    clan_standalone.slot_requested_at = "2026-07-12T12:00:00Z"
    settled_monitor = _monitor_agent("family--mon", family="family", state="completed")
    family_root.followup_agents.append(settled_monitor)
    family_root.runtime_children.append(settled_monitor)
    agents = project_clan_tree(
        [
            standalone,
            family_root,
            family_child,
            clan_family_root,
            clan_family_child,
            clan_standalone,
        ]
    )

    counts = agent_panel_counts(agents, set())

    assert counts.lane_count == 4
    assert counts.queued == 1
    assert (counts.running, counts.waiting, counts.read) == (2, 0, 1)
    assert counts.settled_monitors == 1
    assert counts.running_monitors == 0
    # Disjoint status metrics must sum to the number of visible lanes, even
    # though settled_monitors is populated: monitors are not agents.
    assert sum(value for _name, value in counts.metric_items()) == 4


def test_agent_panel_counts_is_fold_independent_for_settled_monitors() -> None:
    container = _agent(name="alpha--0", suffix="alpha-0", status="RUNNING")
    container.agent_family = "alpha"
    container.agent_family_role = "root"
    monitor = _monitor_agent("alpha--mon", family="alpha", state="completed")
    container.runtime_children = [monitor]
    container.followup_agents = [monitor]

    # Only the container is in the slice, simulating a collapsed fold that
    # hides the monitor row.
    counts = agent_panel_counts([container], set())

    assert counts.settled_monitors == 1


def test_agent_panel_counts_is_fold_independent_for_running_monitors() -> None:
    container = _agent(name="alpha--0", suffix="alpha-0", status="RUNNING")
    container.agent_family = "alpha"
    container.agent_family_role = "root"
    monitor = _monitor_agent("alpha--mon", family="alpha", state="running")
    container.runtime_children = [monitor]
    container.followup_agents = [monitor]

    # Only the container is in the slice, simulating a collapsed fold that
    # hides the monitor row.
    counts = agent_panel_counts([container], set())

    assert counts.running_monitors == 1
    assert counts.settled_monitors == 0


def test_agent_panel_counts_does_not_double_count_clan_and_family_rows() -> None:
    clan = _agent(name="workers", suffix="workers", status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "workers"
    family_root = _agent(
        name="alpha--0",
        suffix="alpha-0",
        status="RUNNING",
        parent_timestamp="workers",
    )
    family_root.agent_family = "alpha"
    family_root.agent_family_role = "root"
    family_root.agent_clan = "workers"
    monitor = _monitor_agent("alpha--mon", family="alpha", state="completed")
    running_monitor = _monitor_agent("alpha--mon-run", family="alpha", state="running")
    family_root.runtime_children = [monitor, running_monitor]
    family_root.followup_agents = [monitor, running_monitor]
    clan.runtime_children = [family_root]

    counts = agent_panel_counts([clan, family_root], set())

    assert (counts.running_monitors, counts.settled_monitors) == (1, 1)


def test_panel_monitor_lanes_match_sum_of_container_row_badges() -> None:
    family_a_root, family_a_child = _sequential_family("alpha")
    monitor_a_running = _monitor_agent(
        "alpha--mon-run", family="alpha", state="running"
    )
    monitor_a_done = _monitor_agent(
        "alpha--mon-done", family="alpha", state="completed"
    )
    family_a_root.followup_agents.extend([monitor_a_running, monitor_a_done])
    family_a_root.runtime_children.extend([monitor_a_running, monitor_a_done])

    family_b_root, family_b_child = _sequential_family("beta")
    monitor_b_done = _monitor_agent("beta--mon-done", family="beta", state="completed")
    family_b_root.followup_agents.append(monitor_b_done)
    family_b_root.runtime_children.append(monitor_b_done)

    agents = [family_a_root, family_a_child, family_b_root, family_b_child]
    counts = agent_panel_counts(agents, set())

    expected_settled = (
        monitor_lane_counts(family_a_root).settled
        + monitor_lane_counts(family_b_root).settled
    )
    expected_running = (
        monitor_lane_counts(family_a_root).running
        + monitor_lane_counts(family_b_root).running
    )
    assert expected_settled == 2
    assert expected_running == 1
    assert counts.settled_monitors == expected_settled
    assert counts.running_monitors == expected_running

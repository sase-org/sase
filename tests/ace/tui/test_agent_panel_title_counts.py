"""Lane and monitor tallies behind Agents-tab panel border titles."""

from __future__ import annotations

from sase.ace.tui.actions.agents._display_panel_titles import agent_panel_counts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_session_members import (
    shell_lane_counts,
)

from ._agent_panel_title_helpers import _agent


def _monitor_lane_counts(agent: Agent):
    return shell_lane_counts(agent).monitor


def _gate_lane_counts(agent: Agent):
    return shell_lane_counts(agent).gate


def _monitor_agent(name: str, *, session: str, state: str | None) -> Agent:
    settled = state not in (None, "running")
    monitor = _agent(
        name=name,
        suffix=name,
        status="MONITORED" if settled else "MONITORING",
    )
    monitor.agent_session = session
    monitor.agent_session_role = "monitor"
    monitor.role_suffix = "--mon"
    monitor.monitor_id = name
    monitor.monitor_state = state
    return monitor


def _gate_agent(name: str, *, session: str, state: str | None) -> Agent:
    settled = state in {"answered", "completed", "stopped"}
    failed = state in {"failed", "timeout", "lost"}
    gate = _agent(
        name=name,
        suffix=name,
        status="GATED" if settled or failed else "GATE",
    )
    gate.agent_session = session
    gate.agent_session_role = "gate"
    gate.role_suffix = "--gate"
    gate.gate_id = name
    gate.gate_kind = "test"
    gate.gate_state = state
    return gate


def _sequential_agent_session(
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
    root.agent_session = name
    root.agent_session_role = "root"
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
    child.agent_session = name
    child.agent_session_role = "code"
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
    agent_session_root, agent_session_child = _sequential_agent_session("session")
    clan_agent_session_root, clan_agent_session_child = _sequential_agent_session(
        "research.session",
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
    settled_monitor = _monitor_agent(
        "session--mon", session="session", state="completed"
    )
    agent_session_root.followup_agents.append(settled_monitor)
    agent_session_root.runtime_children.append(settled_monitor)
    agents = project_clan_tree(
        [
            standalone,
            agent_session_root,
            agent_session_child,
            clan_agent_session_root,
            clan_agent_session_child,
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
    container.agent_session = "alpha"
    container.agent_session_role = "root"
    monitor = _monitor_agent("alpha--mon", session="alpha", state="completed")
    container.runtime_children = [monitor]
    container.followup_agents = [monitor]

    # Only the container is in the slice, simulating a collapsed fold that
    # hides the monitor row.
    counts = agent_panel_counts([container], set())

    assert counts.settled_monitors == 1


def test_agent_panel_counts_is_fold_independent_for_running_monitors() -> None:
    container = _agent(name="alpha--0", suffix="alpha-0", status="RUNNING")
    container.agent_session = "alpha"
    container.agent_session_role = "root"
    monitor = _monitor_agent("alpha--mon", session="alpha", state="running")
    container.runtime_children = [monitor]
    container.followup_agents = [monitor]

    # Only the container is in the slice, simulating a collapsed fold that
    # hides the monitor row.
    counts = agent_panel_counts([container], set())

    assert counts.running_monitors == 1
    assert counts.settled_monitors == 0


def test_agent_panel_counts_is_fold_independent_for_gates() -> None:
    container = _agent(name="alpha--0", suffix="alpha-0", status="RUNNING")
    container.agent_session = "alpha"
    container.agent_session_role = "root"
    pending_gate = _gate_agent("alpha--gate-pending", session="alpha", state="pending")
    settled_gate = _gate_agent("alpha--gate-done", session="alpha", state="answered")
    failed_gate = _gate_agent("alpha--gate-failed", session="alpha", state="failed")
    container.runtime_children = [pending_gate, settled_gate, failed_gate]
    container.followup_agents = [pending_gate, settled_gate, failed_gate]

    counts = agent_panel_counts([container], set())

    assert counts.running_gates == 1
    assert counts.settled_gates == 1
    assert counts.failed_gates == 1
    assert sum(value for _name, value in counts.metric_items()) == counts.lane_count


def test_agent_panel_counts_does_not_double_count_clan_and_agent_session_rows() -> None:
    clan = _agent(name="workers", suffix="workers", status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "workers"
    agent_session_root = _agent(
        name="alpha--0",
        suffix="alpha-0",
        status="RUNNING",
        parent_timestamp="workers",
    )
    agent_session_root.agent_session = "alpha"
    agent_session_root.agent_session_role = "root"
    agent_session_root.agent_clan = "workers"
    monitor = _monitor_agent("alpha--mon", session="alpha", state="completed")
    running_monitor = _monitor_agent("alpha--mon-run", session="alpha", state="running")
    agent_session_root.runtime_children = [monitor, running_monitor]
    agent_session_root.followup_agents = [monitor, running_monitor]
    clan.runtime_children = [agent_session_root]

    counts = agent_panel_counts([clan, agent_session_root], set())

    assert (counts.running_monitors, counts.settled_monitors) == (1, 1)


def test_panel_monitor_lanes_match_sum_of_container_row_badges() -> None:
    agent_session_a_root, agent_session_a_child = _sequential_agent_session("alpha")
    monitor_a_running = _monitor_agent(
        "alpha--mon-run", session="alpha", state="running"
    )
    monitor_a_done = _monitor_agent(
        "alpha--mon-done", session="alpha", state="completed"
    )
    agent_session_a_root.followup_agents.extend([monitor_a_running, monitor_a_done])
    agent_session_a_root.runtime_children.extend([monitor_a_running, monitor_a_done])

    agent_session_b_root, agent_session_b_child = _sequential_agent_session("beta")
    monitor_b_done = _monitor_agent("beta--mon-done", session="beta", state="completed")
    agent_session_b_root.followup_agents.append(monitor_b_done)
    agent_session_b_root.runtime_children.append(monitor_b_done)

    agents = [
        agent_session_a_root,
        agent_session_a_child,
        agent_session_b_root,
        agent_session_b_child,
    ]
    counts = agent_panel_counts(agents, set())

    expected_settled = (
        _monitor_lane_counts(agent_session_a_root).settled
        + _monitor_lane_counts(agent_session_b_root).settled
    )
    expected_running = (
        _monitor_lane_counts(agent_session_a_root).running
        + _monitor_lane_counts(agent_session_b_root).running
    )
    assert expected_settled == 2
    assert expected_running == 1
    assert counts.settled_monitors == expected_settled
    assert counts.running_monitors == expected_running


def test_panel_gate_lanes_match_sum_of_container_row_badges() -> None:
    agent_session_a_root, agent_session_a_child = _sequential_agent_session("alpha")
    gate_a_pending = _gate_agent(
        "alpha--gate-pending", session="alpha", state="pending"
    )
    gate_a_done = _gate_agent("alpha--gate-done", session="alpha", state="answered")
    agent_session_a_root.followup_agents.extend([gate_a_pending, gate_a_done])
    agent_session_a_root.runtime_children.extend([gate_a_pending, gate_a_done])

    agent_session_b_root, agent_session_b_child = _sequential_agent_session("beta")
    gate_b_failed = _gate_agent("beta--gate-failed", session="beta", state="timeout")
    agent_session_b_root.followup_agents.append(gate_b_failed)
    agent_session_b_root.runtime_children.append(gate_b_failed)

    agents = [
        agent_session_a_root,
        agent_session_a_child,
        agent_session_b_root,
        agent_session_b_child,
    ]
    counts = agent_panel_counts(agents, set())

    expected = (
        _gate_lane_counts(agent_session_a_root).running,
        _gate_lane_counts(agent_session_a_root).settled,
        _gate_lane_counts(agent_session_b_root).failed,
    )
    assert expected == (1, 1, 1)
    assert (counts.running_gates, counts.settled_gates, counts.failed_gates) == expected

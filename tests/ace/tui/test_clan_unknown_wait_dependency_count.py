"""Tests for unknown wait-target keys and clan unknown aggregation."""

from __future__ import annotations

from sase.ace.tui.agent_completion import (
    AgentWaitStatusMaps,
    clan_unknown_wait_dependency_count,
    collect_agent_wait_status_maps,
    wait_dependency_status_counts,
    wait_dependency_unknown_targets,
)
from sase.ace.tui.models.agent_wait_beads import (
    WaitBeadStatusSnapshot,
    _WaitBeadStatusSnapshotEntry,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _dep(name: str, bucket: str):
    return make_agent(
        agent_name=name,
        raw_suffix=f"{name}-suffix",
        status="RUNNING",
        status_bucket=bucket,
    )


def _clan_container(*, clan: str = "clan", generation: str = "g"):
    container = make_agent(
        agent_name=None,
        raw_suffix="g",
        agent_clan=clan,
        agent_clan_generation=generation,
        is_clan_container=True,
    )
    container.runtime_children = []
    return container


def _clan_member(*, name: str, status: str = "WAITING", **overrides: object):
    kwargs: dict[str, object] = {
        "agent_name": name,
        "raw_suffix": f"{name}-suffix",
        "agent_clan": "clan",
        "agent_clan_generation": "g",
        "status": status,
    }
    kwargs.update(overrides)
    return make_agent(**kwargs)  # type: ignore[arg-type]


def test_parity_unknown_agent_target() -> None:
    waiter = make_agent(status="WAITING", waiting_for=["ghost"])
    maps = collect_agent_wait_status_maps([waiter])

    counts = wait_dependency_status_counts(waiter, maps)
    targets = wait_dependency_unknown_targets(waiter, maps)

    assert counts.agents.unknown == 1
    assert len(targets) == counts.agents.unknown + counts.beads.unknown
    assert targets == frozenset({("agent", "ghost")})


def test_parity_unknown_clan_member_target() -> None:
    waiter = make_agent(status="WAITING", waiting_for=["clan"])
    maps = AgentWaitStatusMaps(
        buckets={},
        clan_member_statuses={"clan": (("member", "Bogus"),)},
        tribe_bindings={},
    )

    counts = wait_dependency_status_counts(waiter, maps)
    targets = wait_dependency_unknown_targets(waiter, maps)

    assert counts.agents.unknown == 1
    assert targets == frozenset({("agent", "clan:member")})
    assert len(targets) == counts.agents.unknown + counts.beads.unknown


def test_parity_unknown_bead_status() -> None:
    waiter = make_agent(status="WAITING", waiting_for_beads=["bad-bead"])
    maps = collect_agent_wait_status_maps([waiter])
    snapshot = WaitBeadStatusSnapshot(
        (_WaitBeadStatusSnapshotEntry("bad-bead", "unsupported"),)
    )

    counts = wait_dependency_status_counts(waiter, maps, snapshot)
    targets = wait_dependency_unknown_targets(waiter, maps, snapshot)

    assert counts.beads.unknown == 1
    assert targets == frozenset({("bead", "bad-bead")})
    assert len(targets) == counts.agents.unknown + counts.beads.unknown


def test_parity_mixed_unknowns() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=["ghost", "clan"],
        waiting_for_beads=["bad-bead"],
    )
    maps = AgentWaitStatusMaps(
        buckets={},
        clan_member_statuses={"clan": (("m1", "Bogus"), ("m2", "Running"))},
        tribe_bindings={},
    )
    snapshot = WaitBeadStatusSnapshot(
        (_WaitBeadStatusSnapshotEntry("bad-bead", "unsupported"),)
    )

    counts = wait_dependency_status_counts(waiter, maps, snapshot)
    targets = wait_dependency_unknown_targets(waiter, maps, snapshot)

    assert counts.agents.unknown == 2
    assert counts.beads.unknown == 1
    assert targets == frozenset(
        {("agent", "ghost"), ("agent", "clan:m1"), ("bead", "bad-bead")}
    )
    assert len(targets) == counts.agents.unknown + counts.beads.unknown


def test_unknown_targets_skip_tribe_and_cold_beads() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=["@default"],
        waiting_for_beads=["cold", "known"],
    )
    maps = collect_agent_wait_status_maps([waiter])
    snapshot = WaitBeadStatusSnapshot(
        (
            _WaitBeadStatusSnapshotEntry("cold", None, is_cold=True),
            _WaitBeadStatusSnapshotEntry("known", "open"),
        )
    )

    assert wait_dependency_unknown_targets(waiter, maps, snapshot) == frozenset()
    counts = wait_dependency_status_counts(waiter, maps, snapshot)
    assert counts.agents.unknown == 0
    assert counts.beads.unknown == 0


def test_clan_count_zero_for_non_clan() -> None:
    agent = make_agent(status="WAITING", waiting_for=["ghost"])
    maps = collect_agent_wait_status_maps([agent])

    assert clan_unknown_wait_dependency_count(agent, maps) == 0


def test_clan_count_zero_with_no_waiting_members() -> None:
    container = _clan_container()
    running = _clan_member(name="clan.a", status="RUNNING")
    done = _clan_member(name="clan.b", status="DONE")
    container.runtime_children.extend([running, done])
    maps = collect_agent_wait_status_maps([container, running, done])

    assert clan_unknown_wait_dependency_count(container, maps) == 0


def test_clan_count_ignores_non_waiting_member_with_waits() -> None:
    container = _clan_container()
    running = _clan_member(name="clan.a", status="RUNNING", waiting_for=["ghost"])
    container.runtime_children.append(running)
    maps = collect_agent_wait_status_maps([container, running])

    assert clan_unknown_wait_dependency_count(container, maps) == 0


def test_clan_count_dedupes_shared_missing_target() -> None:
    container = _clan_container()
    first = _clan_member(name="clan.a", waiting_for=["ghost"])
    second = _clan_member(name="clan.b", waiting_for=["ghost"])
    container.runtime_children.extend([first, second])
    maps = collect_agent_wait_status_maps([container, first, second])

    assert clan_unknown_wait_dependency_count(container, maps) == 1


def test_clan_count_sums_distinct_agent_and_bead_unknowns() -> None:
    container = _clan_container()
    first = _clan_member(name="clan.a", waiting_for=["ghost"], project_file="")
    second = _clan_member(
        name="clan.b",
        waiting_for_beads=["missing-bead"],
        project_file="",
    )
    container.runtime_children.extend([first, second])
    maps = collect_agent_wait_status_maps([container, first, second])

    assert clan_unknown_wait_dependency_count(container, maps) == 2

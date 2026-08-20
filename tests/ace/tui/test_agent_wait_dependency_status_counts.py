"""Tests for WAITING row dependency status-count projection."""

from __future__ import annotations

from sase.ace.tui.agent_completion import (
    WaitDependencyStatusCounts,
    collect_agent_wait_status_maps,
    wait_dependency_status_counts,
)
from sase.ace.tui.models.agent_wait_beads import (
    WaitBeadStatusSnapshot,
    _WaitBeadStatusSnapshotEntry,
)
from sase.ace.tui.wait_status_presentation import (
    format_wait_dependency_status_counts,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _dep(name: str, bucket: str):
    return make_agent(
        agent_name=name,
        raw_suffix=f"{name}-suffix",
        status="RUNNING",
        status_bucket=bucket,
    )


def test_counts_mix_agents_beads_unknowns_and_stable_order() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=[
            "stopped",
            "failed",
            "starting",
            "running",
            "queued",
            "waiting",
            "done",
            "ghost",
        ],
        waiting_for_beads=[
            "claimed-bead",
            "running-bead",
            "waiting-bead",
            "done-bead",
            "bad-bead",
        ],
    )
    maps = collect_agent_wait_status_maps(
        [
            waiter,
            _dep("stopped", "Stopped"),
            _dep("failed", "Failed"),
            _dep("starting", "Starting"),
            _dep("running", "Running"),
            _dep("queued", "Queued"),
            _dep("waiting", "Waiting"),
            _dep("done", "Done"),
        ]
    )
    bead_snapshot = WaitBeadStatusSnapshot(
        (
            _WaitBeadStatusSnapshotEntry("claimed-bead", "claimed"),
            _WaitBeadStatusSnapshotEntry("running-bead", "in_progress"),
            _WaitBeadStatusSnapshotEntry("waiting-bead", "open"),
            _WaitBeadStatusSnapshotEntry("done-bead", "closed"),
            _WaitBeadStatusSnapshotEntry("bad-bead", "unsupported"),
        )
    )

    counts = wait_dependency_status_counts(waiter, maps, bead_snapshot)

    assert counts == WaitDependencyStatusCounts(
        stopped=1,
        failed=1,
        starting=2,
        running=2,
        queued=1,
        waiting=2,
        done=2,
        unknown=2,
    )
    assert format_wait_dependency_status_counts(counts).plain == (
        "▲1 ✗1 ◐2 ▶2 …1 ⏳2 ✓2 ?2"
    )


def test_formatter_suppresses_zeroes_and_keeps_multi_digit_counts() -> None:
    counts = WaitDependencyStatusCounts(running=12, done=3, unknown=1)

    assert format_wait_dependency_status_counts(counts).plain == "▶12 ✓3 ?1"


def test_cold_bead_cache_miss_is_omitted_until_warm() -> None:
    waiter = make_agent(status="WAITING", waiting_for_beads=["cold", "known"])
    maps = collect_agent_wait_status_maps([waiter])
    bead_snapshot = WaitBeadStatusSnapshot(
        (
            _WaitBeadStatusSnapshotEntry("cold", None, is_cold=True),
            _WaitBeadStatusSnapshotEntry("known", None),
        )
    )

    counts = wait_dependency_status_counts(waiter, maps, bead_snapshot)

    assert counts == WaitDependencyStatusCounts(unknown=1)


def test_clan_wait_counts_expanded_members_not_aggregate() -> None:
    waiter = make_agent(status="WAITING", waiting_for=["clan"])
    container = make_agent(
        agent_name=None,
        raw_suffix="g",
        agent_clan="clan",
        agent_clan_generation="g",
        is_clan_container=True,
    )
    done = make_agent(
        agent_name="clan.done",
        raw_suffix="g-1",
        agent_clan="clan",
        agent_clan_generation="g",
        status="RUNNING",
        status_bucket="Done",
    )
    running = make_agent(
        agent_name="clan.running",
        raw_suffix="g-2",
        agent_clan="clan",
        agent_clan_generation="g",
        status="RUNNING",
        status_bucket="Running",
    )
    failed = make_agent(
        agent_name="clan.failed",
        raw_suffix="g-3",
        agent_clan="clan",
        agent_clan_generation="g",
        status="RUNNING",
        status_bucket="Failed",
    )
    container.runtime_children.extend([done, running, failed])
    maps = collect_agent_wait_status_maps([waiter, container, done, running, failed])

    counts = wait_dependency_status_counts(waiter, maps)

    assert counts == WaitDependencyStatusCounts(failed=1, running=1, done=1)


def test_wait_display_source_owns_counted_dependencies() -> None:
    root = make_agent(status="WAITING", waiting_for=["root-dep"])
    child = make_agent(status="WAITING", waiting_for=["child-dep"])
    root.wait_display_source = child
    maps = collect_agent_wait_status_maps(
        [root, child, _dep("root-dep", "Failed"), _dep("child-dep", "Running")]
    )

    assert wait_dependency_status_counts(root, maps) == WaitDependencyStatusCounts(
        running=1
    )


def test_tribe_time_and_runner_waits_do_not_enter_dependency_counts() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=["@default"],
        wait_duration=300,
        wait_runners=1,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    maps = collect_agent_wait_status_maps([waiter])

    assert wait_dependency_status_counts(waiter, maps) == WaitDependencyStatusCounts()

"""Tests for runner-slot occupancy across families, clans, and monitor handoffs."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._agent_clan import clan_member_counts, sase_agent_status_counts
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.agent.status_buckets import agent_status_bucket

from ._agent_runner_slots_helpers import _agent, _assert_capacity_metrics


def test_refresh_runner_slot_context_counts_one_lane_per_sequential_family() -> None:
    """A live serial child rides its root's slot instead of adding a second one.

    The root's own status already mirrors its newest live descendant (the
    generic family status-propagation pass covered by
    ``test_monitor_family_root_projection.py``), so a bare root plus a live
    serial child is exactly the shape ``refresh_runner_slot_context`` sees
    once the loader has run that propagation.
    """
    root = _agent("root", status="RUNNING")
    serial_child = _agent(
        "serial-child",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        parent_timestamp="root",
    )
    axe = _agent(
        "axe",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        artifacts_dir="/tmp/project/artifacts/crs/axe",
    )
    waiter = _agent(
        "waiter",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context(
        [root, serial_child, axe, waiter], effective_limit=10
    )

    _assert_capacity_metrics(capacity, (10, 1, 1))
    assert waiter.runner_slots_in_use == 1


def test_refresh_runner_slot_context_counts_each_parallel_clan_member() -> None:
    """Each live parallel family member holds its own slot, individually."""
    first = _agent(
        "parallel.first",
        status="RUNNING",
        agent_clan="parallel",
        agent_clan_generation="20260712120000",
    )
    second = _agent(
        "parallel.second",
        status="RUNNING",
        agent_clan="parallel",
        agent_clan_generation="20260712120000",
    )
    projected = project_clan_tree([first, second])

    capacity = refresh_runner_slot_context(projected, effective_limit=10)

    _assert_capacity_metrics(capacity, (10, 2, 0))


def test_refresh_runner_slot_context_counts_monitor_holding_family_slot() -> None:
    """A family whose root died mid-handoff still holds one slot via its monitor.

    ``root`` stands in for a family container whose status already mirrors
    its live monitor member (see ``test_monitor_family_root_projection.py``
    for the propagation this simulates); the monitor's own row is a family
    child and never adds a second lane.
    """
    root = _agent("root", status="MONITORING", status_bucket="Running")
    monitor = _agent(
        "monitor",
        status="MONITORING",
        status_bucket="Running",
        parent_timestamp="root",
        agent_family_role="monitor",
    )

    capacity = refresh_runner_slot_context([root, monitor], effective_limit=10)

    _assert_capacity_metrics(capacity, (10, 1, 0))


def test_refresh_runner_slot_context_counts_post_handoff_followup_family_slot() -> None:
    """A family whose monitor settled and launched a follow-up still holds one slot."""
    root = _agent("root", status="RUNNING")
    followup = _agent(
        "followup",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        parent_timestamp="root",
        agent_family_role="code",
    )

    capacity = refresh_runner_slot_context([root, followup], effective_limit=10)

    _assert_capacity_metrics(capacity, (10, 1, 0))


def test_first_refresh_promotes_all_slot_waiters_and_clan_aggregate() -> None:
    implicit = _agent(
        "research.implicit",
        agent_clan="research",
        agent_clan_generation="20260712120000",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    explicit = _agent(
        "research.explicit",
        agent_clan="research",
        agent_clan_generation="20260712120000",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    projected = project_clan_tree([implicit, explicit])

    first = refresh_runner_slot_context(projected, effective_limit=10)

    _assert_capacity_metrics(first, (10, 0, 2))
    assert projected[0].status == "QUEUED"
    assert (implicit.status, explicit.status) == ("QUEUED", "QUEUED")

    second = refresh_runner_slot_context(projected, effective_limit=10)

    assert second == first
    assert projected[0].status == "QUEUED"
    assert (implicit.status, explicit.status) == ("QUEUED", "QUEUED")


@pytest.mark.parametrize("effective_limit", [None, 10])
def test_first_refresh_promotes_sequential_family_root_from_slot_waiter(
    effective_limit: int | None,
) -> None:
    root = _agent("root", status="DONE", pid=None)
    child = _agent(
        "code",
        status="WAITING",
        start_time=datetime(2026, 7, 12, 12, 1),
        parent_timestamp="root",
        wait_runners=0,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    rows = [root, child]
    _apply_status_overrides(rows)

    if effective_limit is None:
        first = refresh_runner_slot_context(rows)
    else:
        first = refresh_runner_slot_context(rows, effective_limit=effective_limit)

    assert child.status == "QUEUED"
    assert child.runner_slot_queue_position == 1
    assert child.runner_slot_queue_size == 1
    assert root.status == "QUEUED"
    assert root.wait_display_source is child

    if effective_limit is None:
        second = refresh_runner_slot_context(rows)
    else:
        second = refresh_runner_slot_context(rows, effective_limit=effective_limit)

    assert second == first
    assert (root.status, child.status) == ("QUEUED", "QUEUED")
    assert child.runner_slot_queue_position == 1
    assert child.runner_slot_queue_size == 1


@pytest.mark.parametrize("effective_limit", [None, 10])
def test_refresh_keeps_sequential_family_root_waiting_for_non_slot_waiter(
    effective_limit: int | None,
) -> None:
    root = _agent("root", status="DONE", pid=None)
    child = _agent(
        "code",
        status="WAITING",
        start_time=datetime(2026, 7, 12, 12, 1),
        parent_timestamp="root",
    )
    rows = [root, child]
    _apply_status_overrides(rows)

    if effective_limit is None:
        snapshot = refresh_runner_slot_context(rows)
    else:
        snapshot = refresh_runner_slot_context(rows, effective_limit=effective_limit)

    assert len(snapshot.queue) == 0
    assert (root.status, child.status) == ("WAITING", "WAITING")
    assert child.runner_slot_queue_position is None
    assert child.runner_slot_queue_size is None


def _testing_clan_rows():
    testing = _agent(
        "research.testing",
        status="TESTING",
        status_bucket="Running",
        agent_clan="research",
        agent_clan_generation="20260712120000",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="running",
    )
    waiting = _agent(
        "research.waiting",
        agent_clan="research",
        agent_clan_generation="20260712120000",
    )
    return project_clan_tree([testing, waiting])


def _failed_testing_clan_rows():
    tested = _agent(
        "research.tested",
        status="TESTED",
        status_bucket="Failed",
        agent_clan="research",
        agent_clan_generation="20260712120000",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="failed",
    )
    waiting = _agent(
        "research.waiting",
        agent_clan="research",
        agent_clan_generation="20260712120000",
    )
    done = _agent(
        "research.done",
        status="DONE",
        pid=None,
        agent_clan="research",
        agent_clan_generation="20260712120000",
    )
    return project_clan_tree([tested, waiting, done])


def test_refresh_runner_slot_context_keeps_lone_testing_clan_status() -> None:
    fallback_rows = _testing_clan_rows()
    refresh_runner_slot_context(fallback_rows)
    assert fallback_rows[0].status == "TESTING"

    snapshot_rows = _testing_clan_rows()
    refresh_runner_slot_context(snapshot_rows, effective_limit=10)
    assert snapshot_rows[0].status == "TESTING"


@pytest.mark.parametrize("effective_limit", [None, 10])
def test_refresh_runner_slot_context_keeps_lone_failed_testing_clan_status(
    effective_limit: int | None,
) -> None:
    rows = _failed_testing_clan_rows()

    for _ in range(2):
        if effective_limit is None:
            refresh_runner_slot_context(rows)
        else:
            refresh_runner_slot_context(rows, effective_limit=effective_limit)

    clan = rows[0]
    counts = clan_member_counts(clan)
    summary = sase_agent_status_counts(rows, unread_ids=())
    assert clan.status == "TESTED"
    assert agent_status_bucket(clan) == "Failed"
    assert clan.monitor_start_status == "TESTING"
    assert clan.monitor_stop_status == "TESTED"
    assert clan.monitor_state == "failed"
    assert (counts.failed, counts.waiting, counts.done) == (1, 1, 1)
    assert summary.failed == 1

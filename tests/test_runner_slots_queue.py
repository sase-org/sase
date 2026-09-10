"""Unit tests for the runner-slot waiter queue and start admission."""

from __future__ import annotations

from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    RunnerSlotWaiter,
    live_runner_slot_waiters,
    may_start,
)
from tests._runner_slots_helpers import _record


def test_live_waiter_queue_is_fifo_and_filters_stale_processes() -> None:
    records = [
        _record("/later", pid=2, requested_at="2026-07-12T12:00:02+00:00"),
        _record("/earlier", pid=1, requested_at="2026-07-12T12:00:01+00:00"),
        _record("/dead", pid=9, requested_at="2026-07-12T11:00:00+00:00"),
    ]

    queue = live_runner_slot_waiters(
        records,
        lambda record: record.agent_meta.pid != 9,  # type: ignore[union-attr]
    )

    assert [waiter.artifact_dir for waiter in queue] == ["/earlier", "/later"]
    assert [waiter.threshold for waiter in queue] == [0, 0]
    assert [waiter.priority for waiter in queue] == [
        DEFAULT_WAIT_PRIORITY,
        DEFAULT_WAIT_PRIORITY,
    ]


def test_live_waiter_queue_orders_priority_before_fifo() -> None:
    records = [
        _record(
            "/older-default",
            requested_at="2026-07-12T12:00:00+00:00",
            wait_priority=DEFAULT_WAIT_PRIORITY,
        ),
        _record(
            "/newer-urgent",
            requested_at="2026-07-12T12:00:01+00:00",
            wait_priority=1,
        ),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == [
        "/newer-urgent",
        "/older-default",
    ]


def test_live_waiter_queue_preserves_fifo_within_priority() -> None:
    records = [
        _record(
            "/later",
            requested_at="2026-07-12T12:00:02+00:00",
            wait_priority=4,
        ),
        _record(
            "/earlier",
            requested_at="2026-07-12T12:00:01+00:00",
            wait_priority=4,
        ),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == ["/earlier", "/later"]


def test_live_waiter_queue_defaults_missing_or_invalid_priorities() -> None:
    requested_at = "2026-07-12T12:00:00+00:00"
    records = [
        _record("/missing", requested_at=requested_at),
        _record("/boolean", requested_at=requested_at, wait_priority=True),
        _record("/negative", requested_at=requested_at, wait_priority=-1),
        _record("/explicit", requested_at=requested_at, wait_priority=2),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert queue[0].artifact_dir == "/explicit"
    assert {waiter.priority for waiter in queue[1:]} == {DEFAULT_WAIT_PRIORITY}


def test_queue_ties_have_deterministic_timestamp_then_path_order() -> None:
    requested_at = "2026-07-12T12:00:00+00:00"
    records = [
        _record("/z/20260712120001", requested_at=requested_at),
        _record("/b/20260712120000", requested_at=requested_at),
        _record("/a/20260712120000", requested_at=requested_at),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == [
        "/a/20260712120000",
        "/b/20260712120000",
        "/z/20260712120001",
    ]


def test_older_ineligible_drain_waiter_does_not_block_eligible_waiter() -> None:
    drain = RunnerSlotWaiter(
        "/drain",
        "2026-07-12T12:00:00+00:00",
        "1",
        threshold=0,
        priority=1,
    )
    immediate = RunnerSlotWaiter(
        "/immediate",
        "2026-07-12T12:00:01+00:00",
        "2",
        threshold=9,
        priority=20,
    )

    assert not may_start(1, 0, (drain, immediate), "/drain")
    assert may_start(1, 9, (drain, immediate), "/immediate")


def test_fifo_order_is_preserved_among_currently_eligible_waiters() -> None:
    first = RunnerSlotWaiter("/first", "2026-07-12T12:00:00+00:00", "1", threshold=9)
    second = RunnerSlotWaiter("/second", "2026-07-12T12:00:01+00:00", "2", threshold=9)

    assert may_start(0, 0, (), "/new")
    assert not may_start(1, 0, (), "/new")
    assert may_start(1, 9, (first, second), "/first")
    assert not may_start(1, 9, (first, second), "/second")


def test_drain_waiter_wins_deterministically_once_count_reaches_zero() -> None:
    first = RunnerSlotWaiter("/drain", "2026-07-12T12:00:00+00:00", "1", threshold=0)
    second = RunnerSlotWaiter(
        "/immediate", "2026-07-12T12:00:01+00:00", "2", threshold=9
    )

    assert may_start(0, 0, (first, second), "/drain")
    assert not may_start(0, 25, (first, second), "/second")


def test_live_waiter_queue_excludes_terminal_records_and_includes_reacquiring_child() -> (
    None
):
    requested_at = "2026-07-12T12:00:00+00:00"
    records = [
        _record("/root", requested_at=requested_at, wait_runners=4),
        _record("/dead", pid=9, requested_at=requested_at, wait_runners=4),
        _record(
            "/child",
            requested_at=requested_at,
            wait_runners=4,
            parent_timestamp="parent",
        ),
        _record(
            "/step",
            requested_at=requested_at,
            wait_runners=4,
            appears_as_agent=False,
        ),
        _record("/done", requested_at=requested_at, wait_runners=4, done=True),
    ]

    queue = live_runner_slot_waiters(
        records,
        lambda record: record.agent_meta.pid != 9,  # type: ignore[union-attr]
    )

    assert [waiter.artifact_dir for waiter in queue] == ["/child", "/root"]
    assert [waiter.threshold for waiter in queue] == [4, 4]


def test_released_serial_successor_and_parallel_member_join_fifo_queue() -> None:
    records = [
        _record(
            "/serial",
            requested_at="2026-07-12T12:00:00+00:00",
            parent_timestamp="parent",
        ),
        _record(
            "/parallel",
            requested_at="2026-07-12T12:00:01+00:00",
            parent_timestamp="parent",
            agent_family_parallel=True,
        ),
        _record("/root", requested_at="2026-07-12T12:00:02+00:00"),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == [
        "/serial",
        "/parallel",
        "/root",
    ]
    assert may_start(0, 0, queue, "/serial")
    assert not may_start(0, 0, queue, "/root")


def test_serial_child_reuses_active_family_claim_without_queue_entry() -> None:
    records = [
        _record(
            "/parent",
            run_started=True,
            agent_family="fam",
        ),
        _record(
            "/serial",
            requested_at="2026-07-12T12:00:00+00:00",
            parent_timestamp="parent",
            agent_family="fam",
        ),
        _record(
            "/parallel",
            requested_at="2026-07-12T12:00:01+00:00",
            parent_timestamp="parent",
            agent_family="fam",
            agent_family_parallel=True,
        ),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == ["/parallel"]

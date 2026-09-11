"""Tests for runner-slot queue ordering: FIFO position, priority, and admission path."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context

from ._agent_runner_slots_helpers import _agent, _assert_capacity_metrics


def test_refresh_runner_slot_context_ranks_all_waiters_while_pool_is_full() -> None:
    running = _agent(
        "running",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
    )
    second = _agent(
        "second",
        wait_runners=0,
        wait_runners_explicit=True,
        wait_priority=1,
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    first = _agent(
        "first",
        wait_runners=9,
        wait_priority=20,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context([running, second, first], effective_limit=10)

    _assert_capacity_metrics(capacity, (10, 1, 2))
    assert first.runner_slots_in_use == 1
    assert first.status == "QUEUED"
    assert first.runner_slot_queue_position == 1
    assert first.runner_slot_queue_size == 2
    assert second.runner_slots_in_use == 1
    assert second.status == "QUEUED"
    assert second.runner_slot_queue_position == 2
    assert second.runner_slot_queue_size == 2
    assert [entry.presented_name for entry in capacity.queue] == ["first", "second"]
    assert [entry.parked for entry in capacity.queue] == [False, True]


def test_refresh_runner_slot_context_orders_mixed_thresholds_by_admission_path() -> (
    None
):
    holders = [
        _agent(
            f"holder-{index}",
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 40 + index),
        )
        for index in range(9)
    ]
    barriers = [
        _agent(
            f"barrier-{index}",
            wait_runners=0,
            wait_runners_explicit=True,
            wait_priority=1,
            slot_requested_at=f"2026-07-12T12:00:0{index}Z",
        )
        for index in range(4)
    ]
    implicit_waiters = [
        _agent(
            "x0",
            wait_runners=9,
            wait_runners_explicit=False,
            slot_requested_at="2026-07-12T12:00:04Z",
        ),
        _agent(
            "x1",
            wait_runners=9,
            wait_runners_explicit=False,
            slot_requested_at="2026-07-12T12:00:05Z",
        ),
    ]

    capacity = refresh_runner_slot_context(
        [*holders, *barriers, *implicit_waiters],
        effective_limit=10,
    )

    assert [entry.presented_name for entry in capacity.queue] == [
        "x0",
        "x1",
        "barrier-0",
        "barrier-1",
        "barrier-2",
        "barrier-3",
    ]
    assert [entry.parked for entry in capacity.queue] == [
        False,
        False,
        True,
        True,
        True,
        True,
    ]
    assert [agent.runner_slot_queue_position for agent in implicit_waiters] == [1, 2]
    assert [agent.runner_slot_queue_position for agent in barriers] == [3, 4, 5, 6]


def test_runner_slot_context_orders_priority_before_fifo() -> None:
    older = _agent(
        "older",
        wait_runners=9,
        wait_priority=20,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    newer = _agent(
        "newer",
        wait_runners=9,
        wait_priority=1,
        slot_requested_at="2026-07-12T12:00:02Z",
    )

    refresh_runner_slot_context([older, newer], effective_limit=10)

    assert newer.runner_slot_queue_position == 1
    assert older.runner_slot_queue_position == 2


def test_runner_slot_context_defaults_missing_and_invalid_priorities() -> None:
    missing = _agent(
        "missing",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    invalid_boolean = _agent(
        "invalid-boolean",
        wait_runners=9,
        wait_priority=True,
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    invalid_negative = _agent(
        "invalid-negative",
        wait_runners=9,
        wait_priority=-1,
        slot_requested_at="2026-07-12T12:00:03Z",
    )
    explicit_default = _agent(
        "explicit-default",
        wait_runners=9,
        wait_priority=10,
        slot_requested_at="2026-07-12T12:00:04Z",
    )
    explicit_priority = _agent(
        "explicit-priority",
        wait_runners=9,
        wait_priority=2,
        slot_requested_at="2026-07-12T12:00:05Z",
    )

    refresh_runner_slot_context(
        [
            missing,
            invalid_boolean,
            invalid_negative,
            explicit_default,
            explicit_priority,
        ],
        effective_limit=10,
    )

    assert explicit_priority.runner_slot_queue_position == 1
    assert missing.runner_slot_queue_position == 2
    assert invalid_boolean.runner_slot_queue_position == 3
    assert invalid_negative.runner_slot_queue_position == 4
    assert explicit_default.runner_slot_queue_position == 5


def test_drain_waiter_joins_fifo_order_when_running_count_reaches_zero() -> None:
    second = _agent(
        "second",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    first = _agent(
        "first",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context([second, first], effective_limit=10)

    _assert_capacity_metrics(capacity, (10, 0, 2))
    assert first.runner_slot_queue_position == 1
    assert first.runner_slot_queue_size == 2
    assert second.runner_slot_queue_position == 2
    assert second.runner_slot_queue_size == 2

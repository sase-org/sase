"""Tests for runner-slot capacity limits and fractional queue-weight handling."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    refresh_runner_slot_context,
)

from ._agent_runner_slots_helpers import _agent, _assert_capacity_metrics


def test_runner_capacity_uses_source_roster_before_display_filtering() -> None:
    holder = _agent(
        "holder",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
    )
    waiter = _agent(
        "waiter",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:00Z",
    )

    capacity = refresh_runner_slot_context(
        [waiter],
        capacity_agents=[holder, waiter],
        effective_limit=1,
    )

    _assert_capacity_metrics(capacity, (1, 1, 1))
    assert capacity.occupied_capacity == 1.0
    assert waiter.status == "QUEUED"
    assert waiter.runner_slot_queue_position == 1
    assert waiter.runner_slot_queue_size == 1
    assert waiter.runner_capacity_blockers[0]["code"] == "insufficient-capacity"


def test_runner_capacity_reports_over_limit_without_clamping() -> None:
    holders = [
        _agent(
            f"holder-{index}",
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 50 + index),
        )
        for index in range(2)
    ]

    capacity = refresh_runner_slot_context(holders, effective_limit=1)

    assert capacity == RunnerCapacitySnapshot(1, 2, 0, occupied_capacity=2.0)


def test_weighted_capacity_reports_fractional_usage_and_blockers() -> None:
    running = _agent(
        "running",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        queue_weight=0.75,
        queue_weight_explicit=True,
    )
    heavy = _agent(
        "heavy",
        queue_weight=0.5,
        queue_weight_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    light = _agent(
        "light",
        queue_weight=0.25,
        queue_weight_explicit=True,
        slot_requested_at="2026-07-12T12:00:02Z",
    )

    capacity = refresh_runner_slot_context(
        [running, heavy, light],
        effective_limit=1,
    )

    _assert_capacity_metrics(capacity, (1, 1, 2))
    assert capacity.occupied_capacity == 0.75
    assert [
        (entry.presented_name, entry.requested_weight) for entry in capacity.queue
    ] == [
        ("light", 0.25),
        ("heavy", 0.5),
    ]
    assert [entry.parked for entry in capacity.queue] == [False, True]
    assert light.runner_slot_queue_position == 1
    assert heavy.runner_slot_queue_position == 2
    assert heavy.runner_capacity_blockers
    assert heavy.runner_capacity_blockers[0]["code"] == "insufficient-capacity"


def test_weight_exceeding_limit_is_parked_with_blocker() -> None:
    heavy = _agent(
        "heavy",
        queue_weight=2.0,
        queue_weight_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context([heavy], effective_limit=1)

    assert capacity.queue[0].requested_weight == 2.0
    assert capacity.queue[0].parked is True
    assert capacity.queue[0].blockers[0]["code"] == "weight-exceeds-limit"
    assert heavy.runner_capacity_blockers[0]["code"] == "weight-exceeds-limit"

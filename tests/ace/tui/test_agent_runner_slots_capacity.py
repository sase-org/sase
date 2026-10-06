"""Tests for runner-slot capacity limits and fractional queue-weight handling."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    format_queue_weight_badge_value,
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


def test_waiter_projection_keeps_admission_limit_separate_from_global_limit() -> None:
    holder = _agent(
        "holder",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        queue_weight=3.0,
        queue_weight_explicit=True,
    )
    waiter = _agent(
        "waiter",
        wait_runners=4,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:00Z",
    )

    capacity = refresh_runner_slot_context([holder, waiter], effective_limit=10)

    assert capacity.effective_limit == 10.0
    assert capacity.occupied_capacity == 3.0
    assert capacity.queue[0].admission_limit == 4.0
    assert capacity.queue[0].occupied_capacity == 3.0
    assert waiter.runner_admission_limit == 4.0
    assert waiter.runner_effective_limit == 10.0


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


def test_queue_weight_badge_shows_explicit_zero() -> None:
    assert format_queue_weight_badge_value(0.0, explicit=True) == "0"
    assert format_queue_weight_badge_value(0.0) is None
    assert format_queue_weight_badge_value(1.0, explicit=True) is None


def test_explicit_zero_waiter_keeps_requested_weight() -> None:
    holder = _agent(
        "holder",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    waiter = _agent(
        "zero",
        queue_weight=0.0,
        queue_weight_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context([holder, waiter], effective_limit=2)

    assert capacity.queue[0].requested_weight == 0.0
    assert capacity.queue[0].requested_weight_explicit is True
    assert capacity.queue[0].parked is False


def _incident_agents(*, ghost_pid: int = 99_999_999) -> list:
    agents = [
        _agent(
            f"research-{index}",
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 59),
            queue_weight=0.25,
            queue_weight_explicit=True,
            pid=100 + index,
        )
        for index in range(5)
    ]
    agents.append(
        _agent(
            "epic-one",
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 59),
            pid=200,
        )
    )
    agents.append(
        _agent(
            "epic-two",
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 59),
            pid=201,
        )
    )
    ghost = _agent(
        "ghost",
        status="TALE APPROVED",
        run_start_time=datetime(2026, 7, 12, 11, 50),
        pid=ghost_pid,
    )
    ghost.pid_liveness_unverified = True
    agents.append(ghost)
    return agents


def test_stamped_ghost_with_dead_pid_is_excluded() -> None:
    capacity = refresh_runner_slot_context(
        _incident_agents(),
        effective_limit=8,
        is_pid_live=lambda _pid: False,
    )

    assert capacity.occupied_capacity == 3.25
    assert capacity.slots_in_use == 7


def test_stamped_row_with_live_pid_is_counted() -> None:
    capacity = refresh_runner_slot_context(
        _incident_agents(),
        effective_limit=8,
        is_pid_live=lambda _pid: True,
    )

    assert capacity.occupied_capacity == 4.25
    assert capacity.slots_in_use == 8


def test_unstamped_rows_never_call_the_probe() -> None:
    def _boom(pid: int) -> bool:
        raise AssertionError(f"probe must not run for pid {pid}")

    agents = [
        _agent(
            "plain",
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 59),
        )
    ]
    capacity = refresh_runner_slot_context(
        agents,
        effective_limit=8,
        is_pid_live=_boom,
    )

    assert capacity.occupied_capacity == 1.0


def test_stamped_done_row_never_calls_the_probe() -> None:
    def _boom(pid: int) -> bool:
        raise AssertionError(f"probe must not run for pid {pid}")

    ghost = _agent("ghost", status="DONE", pid=99_999_999)
    ghost.pid_liveness_unverified = True
    capacity = refresh_runner_slot_context(
        [ghost],
        effective_limit=8,
        is_pid_live=_boom,
    )

    assert capacity.occupied_capacity in (0.0, None)
    assert capacity.slots_in_use == 0


def test_holders_order_monitor_claim_first() -> None:
    monitor = _agent(
        "sess--mon",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        agent_session="sess",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state="running",
        agent_name="sess--mon",
    )
    light = _agent(
        "light",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        queue_weight=0.25,
        queue_weight_explicit=True,
        agent_name="light",
    )

    capacity = refresh_runner_slot_context(
        [monitor, light],
        effective_limit=8,
        is_pid_live=lambda _pid: True,
    )

    assert [(holder.label, holder.weight) for holder in capacity.holders] == [
        ("sess--mon", 1.0),
        ("light", 0.25),
    ]
    assert capacity.holders[0].kind == "monitor"
    assert capacity.holders[1].kind is None

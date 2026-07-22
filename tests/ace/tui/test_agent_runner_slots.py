"""Tests for in-memory Agents-tab runner-slot display context."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    refresh_runner_slot_context,
)


def _agent(name: str, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/project/project.sase",
        "status": "WAITING",
        "start_time": datetime(2026, 7, 12, 12, 0),
        "raw_suffix": name,
        "pid": 100,
        "artifacts_dir": f"/tmp/project/artifacts/ace-run/{name}",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def test_refresh_runner_slot_context_orders_currently_eligible_waiters() -> None:
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

    assert capacity == RunnerCapacitySnapshot(10, 1, 1)
    assert first.runner_slots_in_use == 1
    assert first.runner_slot_queue_position == 1
    assert first.runner_slot_queue_size == 1
    assert second.runner_slots_in_use == 1
    assert second.runner_slot_queue_position is None
    assert second.runner_slot_queue_size == 1


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

    assert capacity == RunnerCapacitySnapshot(10, 0, 1)
    assert first.runner_slot_queue_position == 1
    assert first.runner_slot_queue_size == 2
    assert second.runner_slot_queue_position == 2
    assert second.runner_slot_queue_size == 2


def test_refresh_runner_slot_context_counts_parallel_family_children_only() -> None:
    serial_child = _agent(
        "serial-child",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        parent_timestamp="parent",
    )
    parallel_child = _agent(
        "parallel-child",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 58),
        parent_timestamp="parent",
        agent_family_parallel=True,
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
        [serial_child, parallel_child, axe, waiter], effective_limit=10
    )

    assert capacity == RunnerCapacitySnapshot(10, 1, 1)
    assert waiter.runner_slots_in_use == 1


def test_question_paused_root_is_excluded_from_displayed_occupancy() -> None:
    running = _agent(
        "running",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
    )
    paused = _agent(
        "paused",
        status="QUESTION",
        run_start_time=datetime(2026, 7, 12, 11, 58),
        runner_slot_yielded=True,
    )
    answered_waiter = _agent(
        "answered",
        status="WAITING",
        run_start_time=datetime(2026, 7, 12, 11, 57),
        runner_slot_yielded=True,
        wait_runners=1,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context(
        [running, paused, answered_waiter], effective_limit=10
    )

    assert capacity == RunnerCapacitySnapshot(10, 1, 1)
    assert answered_waiter.runner_slots_in_use == 1
    assert answered_waiter.runner_slot_queue_position == 1


def test_runner_capacity_empty_pool_and_neutral_fallback() -> None:
    assert refresh_runner_slot_context([], effective_limit=7) == (
        RunnerCapacitySnapshot(7, 0, 0)
    )
    assert refresh_runner_slot_context([]) == RunnerCapacitySnapshot()


def test_runner_capacity_excludes_non_slot_and_explicit_waits_from_global_queue() -> (
    None
):
    implicit = _agent(
        "implicit",
        wait_runners=9,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    explicit = _agent(
        "explicit",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    dependency_wait = _agent(
        "dependency",
        waiting_for=["other-agent"],
        slot_requested_at=None,
    )

    capacity = refresh_runner_slot_context(
        [explicit, dependency_wait, implicit], effective_limit=10
    )

    assert capacity == RunnerCapacitySnapshot(10, 0, 1)
    assert implicit.runner_slot_queue_position == 1
    assert explicit.runner_slot_queue_position == 2
    assert implicit.runner_slot_queue_size == 2
    assert explicit.runner_slot_queue_size == 2
    assert dependency_wait.runner_slot_queue_position is None


def test_runner_capacity_counts_only_live_rows_and_excludes_yielded_question() -> None:
    live_holder = _agent(
        "live-holder",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
    )
    dead_holder = _agent(
        "dead-holder",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 58),
        pid=None,
    )
    dead_waiter = _agent(
        "dead-waiter",
        pid=None,
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    yielded_question = _agent(
        "question",
        status="QUESTION",
        run_start_time=datetime(2026, 7, 12, 11, 57),
        runner_slot_yielded=True,
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:02Z",
    )

    capacity = refresh_runner_slot_context(
        [dead_waiter, yielded_question, dead_holder, live_holder],
        effective_limit=10,
    )

    assert capacity == RunnerCapacitySnapshot(10, 1, 0)


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

    assert capacity == RunnerCapacitySnapshot(1, 2, 0)

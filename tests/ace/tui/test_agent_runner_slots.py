"""Tests for in-memory Agents-tab runner-slot display context."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context


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
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    first = _agent(
        "first",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    refresh_runner_slot_context([running, second, first])

    assert first.runner_slots_in_use == 1
    assert first.runner_slot_queue_position == 1
    assert first.runner_slot_queue_size == 1
    assert second.runner_slots_in_use == 1
    assert second.runner_slot_queue_position is None
    assert second.runner_slot_queue_size == 1


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

    refresh_runner_slot_context([second, first])

    assert first.runner_slot_queue_position == 1
    assert first.runner_slot_queue_size == 2
    assert second.runner_slot_queue_position == 2
    assert second.runner_slot_queue_size == 2


def test_refresh_runner_slot_context_excludes_children_and_non_ace_rows() -> None:
    child = _agent(
        "child",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
        parent_timestamp="parent",
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

    refresh_runner_slot_context([child, axe, waiter])

    assert waiter.runner_slots_in_use == 0


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

    refresh_runner_slot_context([running, paused, answered_waiter])

    assert answered_waiter.runner_slots_in_use == 1
    assert answered_waiter.runner_slot_queue_position == 1

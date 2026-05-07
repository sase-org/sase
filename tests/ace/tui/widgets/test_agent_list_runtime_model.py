"""Tests for agent row runtime calculation and ticking decisions."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import compute_row_runtime
from sase.ace.tui.models.agent_time import (
    _format_finish_timestamp,
    runtime_suffix_ticks,
)

from .agent_list_runtime_helpers import (
    agent,
    linked_followup_workflow,
    workflow_child,
)


def test__format_finish_timestamp_same_day() -> None:
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("", "20:17:03")


def test__format_finish_timestamp_prior_day_same_year() -> None:
    stop = datetime(2026, 4, 24, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("Apr 24 ", "20:17")


def test__format_finish_timestamp_prior_year() -> None:
    stop = datetime(2025, 12, 31, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    assert _format_finish_timestamp(stop, now=now) == ("Dec 31 '25", "")


def test_compute_row_runtime_active_returns_elapsed_only() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 38, 45)
    ts, elapsed = compute_row_runtime(agent(start=start), now=now)
    assert ts is None
    assert elapsed == "38m45s"


def test_compute_row_runtime_uses_run_start_when_present() -> None:
    """A long WAIT period should not inflate runtime."""
    start = datetime(2026, 4, 25, 13, 0, 0)
    run_start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    ts, elapsed = compute_row_runtime(agent(start=start, run_start=run_start), now=now)
    assert ts is None
    assert elapsed == "5m"


def test_compute_row_runtime_finished_today() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    ts, elapsed = compute_row_runtime(
        agent(status="DONE", start=start, stop=stop), now=now
    )
    assert ts == ("", "20:17:03")
    # >= 1h: hours and minutes
    assert elapsed == "6h17m"


def test_compute_row_runtime_finished_yesterday() -> None:
    start = datetime(2026, 4, 24, 19, 38, 18)
    stop = datetime(2026, 4, 24, 20, 17, 3)
    now = datetime(2026, 4, 25, 9, 0, 0)
    ts, elapsed = compute_row_runtime(
        agent(status="DONE", start=start, stop=stop), now=now
    )
    assert ts == ("Apr 24 ", "20:17")
    assert elapsed == "38m45s"


def test_compute_row_runtime_no_start_returns_nones() -> None:
    ts, elapsed = compute_row_runtime(agent(start=None), now=datetime.now())
    assert ts is None
    assert elapsed is None


def test_compute_row_runtime_pure_waiting_returns_nones() -> None:
    """A WAITING agent that hasn't started yet renders no runtime suffix."""
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    ts, elapsed = compute_row_runtime(
        agent(status="WAITING", start=start, run_start=None), now=now
    )
    assert ts is None
    assert elapsed is None


def test_compute_row_runtime_workflow_agent_step_returns_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 2, 5)
    ts, elapsed = compute_row_runtime(
        workflow_child(step_type="agent", start=start), now=now
    )
    assert ts is None
    assert elapsed == "2m05s"


def test_compute_row_runtime_linked_followup_workflow_returns_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 2, 5)
    ts, elapsed = compute_row_runtime(linked_followup_workflow(start=start), now=now)
    assert ts is None
    assert elapsed == "2m05s"


def test_compute_row_runtime_prompt_step_done_has_static_suffix() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    run_start = datetime(2026, 4, 25, 14, 1, 0)
    stop = datetime(2026, 4, 25, 14, 2, 30)
    now = datetime(2026, 4, 25, 14, 3, 0)
    ts, elapsed = compute_row_runtime(
        workflow_child(
            step_type="agent",
            status="DONE",
            start=start,
            run_start=run_start,
            stop=stop,
            cl_name="main",
            parent_appears_as_agent=True,
        ),
        now=now,
    )
    assert ts == ("", "14:02:30")
    assert elapsed == "1m30s"


def test_compute_row_runtime_done_plan_step_uses_latest_plan_time() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    now = datetime(2026, 5, 6, 13, 15, 27)
    ts, elapsed = compute_row_runtime(
        workflow_child(
            step_type="agent",
            status="DONE",
            start=start,
            run_start=run_start,
            plan_times=[datetime(2026, 5, 6, 13, 12, 0), plan],
            cl_name="plan",
            parent_appears_as_agent=True,
        ),
        now=now,
    )
    assert ts == ("", "13:14:53")
    assert elapsed == "4m46s"


def test_compute_row_runtime_stop_time_wins_over_plan_time() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    stop = datetime(2026, 5, 6, 13, 13, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    now = datetime(2026, 5, 6, 13, 15, 27)
    ts, elapsed = compute_row_runtime(
        agent(
            status="DONE",
            start=start,
            run_start=run_start,
            stop=stop,
            plan_times=[plan],
        ),
        now=now,
    )
    assert ts == ("", "13:13:07")
    assert elapsed == "3m"


@pytest.mark.parametrize("step_type", ["python", "bash"])
def test_compute_row_runtime_non_agent_workflow_child_returns_nones(
    step_type: str,
) -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 2, 5)
    ts, elapsed = compute_row_runtime(
        workflow_child(step_type=step_type, start=start), now=now
    )
    assert ts is None
    assert elapsed is None


@pytest.mark.parametrize("status", ["PLAN APPROVED", "LEGEND APPROVED"])
def test_runtime_suffix_ticks_active_parent_status(status: str) -> None:
    result = agent(status=status)
    assert runtime_suffix_ticks(result) is True


def test_runtime_suffix_ticks_parent_with_active_followup() -> None:
    parent = agent(status="PLANNING")
    child = agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    parent.followup_agents.append(child)

    assert runtime_suffix_ticks(parent) is True


def test_runtime_suffix_ticks_stopped_parent_with_active_followup_is_stable() -> None:
    parent = agent(
        status="PLAN APPROVED",
        stop=datetime(2026, 4, 25, 14, 31, 0),
    )
    child = agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    parent.followup_agents.append(child)

    assert runtime_suffix_ticks(parent) is False


def test_runtime_suffix_ticks_workflow_child_agent_step_ticks() -> None:
    result = workflow_child(step_type="agent", status="RUNNING")
    assert runtime_suffix_ticks(result) is True


def test_runtime_suffix_ticks_linked_followup_workflow_ticks() -> None:
    result = linked_followup_workflow(status="RUNNING")
    assert runtime_suffix_ticks(result) is True


def test_runtime_suffix_ticks_appears_as_agent_prompt_step_done_is_static() -> None:
    result = workflow_child(
        step_type="agent",
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 2, 30),
        cl_name="main",
        parent_appears_as_agent=True,
    )
    assert runtime_suffix_ticks(result) is False


@pytest.mark.parametrize("step_type", ["python", "bash"])
def test_runtime_suffix_ticks_non_agent_workflow_child_does_not_tick(
    step_type: str,
) -> None:
    result = workflow_child(step_type=step_type, status="RUNNING")
    assert runtime_suffix_ticks(result) is False

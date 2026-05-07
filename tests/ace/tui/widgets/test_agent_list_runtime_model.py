"""Tests for agent row runtime calculation and ticking decisions."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import compute_row_runtime
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models._agent_ordering import sort_and_reorder
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


def test_compute_row_runtime_aggregates_completed_and_active_children() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLAN APPROVED",
        start=datetime(2026, 5, 6, 13, 9, 0),
    )
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 5, 6, 13, 9, 0),
        run_start=datetime(2026, 5, 6, 13, 10, 7),
        plan_times=[datetime(2026, 5, 6, 13, 13, 3)],
        cl_name="plan",
    )
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 5, 6, 13, 13, 10),
        run_start=datetime(2026, 5, 6, 13, 13, 10),
        raw_suffix="20260506131310",
        cl_name="demo.code",
    )
    parent.runtime_children.extend([planner, coder])

    ts, elapsed = compute_row_runtime(parent, now=datetime(2026, 5, 6, 13, 16, 15))

    assert ts is None
    assert elapsed == "6m01s"


def test_compute_row_runtime_plan_approved_uses_segmented_parent_times() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    code = datetime(2026, 5, 6, 13, 15, 10)
    now = datetime(2026, 5, 6, 13, 16, 15)

    ts, elapsed = compute_row_runtime(
        agent(
            agent_type=AgentType.WORKFLOW,
            status="PLAN APPROVED",
            start=start,
            run_start=run_start,
            plan_times=[
                datetime(2026, 5, 6, 13, 12, 0),
                plan,
                datetime(2026, 5, 6, 13, 16, 0),
            ],
            code_time=code,
        ),
        now=now,
    )

    assert ts is None
    assert elapsed == "5m51s"


def test_compute_row_runtime_planning_parent_with_completed_child_is_stable() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLANNING",
        start=datetime(2026, 5, 6, 13, 9, 0),
    )
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 5, 6, 13, 9, 0),
        run_start=datetime(2026, 5, 6, 13, 10, 0),
        plan_times=[datetime(2026, 5, 6, 13, 12, 30)],
        cl_name="plan",
    )
    parent.runtime_children.append(planner)

    ts, elapsed = compute_row_runtime(parent, now=datetime(2026, 5, 6, 13, 30, 0))

    assert ts == ("", "13:12:30")
    assert elapsed == "2m30s"
    assert runtime_suffix_ticks(parent) is False


def test_compute_row_runtime_question_parent_without_child_does_not_tick() -> None:
    result = agent(
        agent_type=AgentType.WORKFLOW,
        status="QUESTION",
        start=datetime(2026, 5, 6, 13, 9, 0),
    )

    assert compute_row_runtime(result, now=datetime(2026, 5, 6, 13, 30, 0)) == (
        None,
        None,
    )
    assert runtime_suffix_ticks(result) is False


def test_compute_row_runtime_waiting_input_parent_without_child_does_not_tick() -> None:
    result = agent(
        agent_type=AgentType.WORKFLOW,
        status="WAITING INPUT",
        start=datetime(2026, 5, 6, 13, 9, 0),
    )

    assert compute_row_runtime(result, now=datetime(2026, 5, 6, 13, 30, 0)) == (
        None,
        None,
    )
    assert runtime_suffix_ticks(result) is False


def test_compute_row_runtime_prerun_waiting_child_contributes_zero() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLANNING",
        start=datetime(2026, 5, 6, 13, 9, 0),
    )
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 5, 6, 13, 9, 0),
        run_start=datetime(2026, 5, 6, 13, 10, 0),
        plan_times=[datetime(2026, 5, 6, 13, 12, 0)],
        cl_name="plan",
    )
    waiting = agent(
        status="WAITING",
        start=datetime(2026, 5, 6, 13, 20, 0),
        run_start=None,
        raw_suffix="20260506132000",
        cl_name="queued",
    )
    parent.runtime_children.extend([planner, waiting])

    ts, elapsed = compute_row_runtime(parent, now=datetime(2026, 5, 6, 13, 30, 0))

    assert ts == ("", "13:12:00")
    assert elapsed == "2m"


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
def test_runtime_suffix_ticks_parent_status_alone_is_stable(status: str) -> None:
    result = agent(status=status)
    assert runtime_suffix_ticks(result) is False


def test_runtime_suffix_ticks_plan_approved_with_segmented_parent_times() -> None:
    result = agent(
        status="PLAN APPROVED",
        plan_times=[datetime(2026, 5, 6, 13, 14, 53)],
        code_time=datetime(2026, 5, 6, 13, 15, 10),
    )
    assert runtime_suffix_ticks(result) is True


def test_runtime_suffix_ticks_parent_with_active_runtime_child() -> None:
    parent = agent(status="PLANNING")
    child = agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    parent.runtime_children.append(child)

    assert runtime_suffix_ticks(parent) is True


def test_runtime_suffix_ticks_stopped_parent_without_runtime_child_is_stable() -> None:
    parent = agent(
        status="PLAN APPROVED",
        stop=datetime(2026, 4, 25, 14, 31, 0),
    )
    child = agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    parent.followup_agents.append(child)

    assert runtime_suffix_ticks(parent) is False


def test_sort_and_reorder_populates_runtime_children_idempotently() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        raw_suffix="20260425140000",
        cl_name="parent",
    )
    planner = workflow_child(
        step_type="agent",
        raw_suffix="20260425140100",
        cl_name="plan",
    )
    shell = workflow_child(
        step_type="bash",
        raw_suffix="20260425140200",
        cl_name="shell",
    )
    embedded = workflow_child(
        step_type="agent",
        raw_suffix="20260425140300",
        cl_name="embedded",
    )
    embedded.parent_step_index = 0
    coder = agent(
        raw_suffix="20260425140400",
        cl_name="code",
    )
    coder.parent_timestamp = "20260425140000"

    sort_and_reorder([parent, coder], [planner, shell, embedded])
    sort_and_reorder([parent, coder], [planner, shell, embedded])

    assert parent.runtime_children == [planner, coder]


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

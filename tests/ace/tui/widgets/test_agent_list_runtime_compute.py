"""Tests for direct agent row runtime calculation."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, compute_row_runtime
from sase.ace.tui.models.agent_time import (
    compute_leaf_row_runtime,
    compute_lowest_row_runtime,
    runtime_suffix_ticks,
)

from .agent_list_runtime_helpers import (
    agent,
    family_container,
    gate_shell,
    linked_followup_workflow,
    monitor_shell,
    workflow_child,
)


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


def test_compute_row_runtime_running_without_run_start_returns_nones() -> None:
    start = datetime(2026, 4, 25, 13, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    ts, elapsed = compute_row_runtime(agent(start=start, run_start=None), now=now)
    assert ts is None
    assert elapsed is None
    assert runtime_suffix_ticks(agent(start=start, run_start=None)) is False


def test_compute_row_runtime_starting_returns_nones() -> None:
    start = datetime(2026, 4, 25, 13, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    ts, elapsed = compute_row_runtime(
        agent(status="STARTING", start=start, run_start=None), now=now
    )
    assert ts is None
    assert elapsed is None
    assert (
        runtime_suffix_ticks(agent(status="STARTING", start=start, run_start=None))
        is False
    )


def test_compute_row_runtime_finished_today() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    ts, elapsed = compute_row_runtime(
        agent(status="DONE", start=start, stop=stop), now=now
    )
    assert ts == ("", "20:17:03")
    assert elapsed == "6h17m"


def test_compute_row_runtime_terminal_without_run_start_falls_back_to_start() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    stop = datetime(2026, 4, 25, 20, 17, 3)
    now = datetime(2026, 4, 25, 21, 0, 0)
    ts, elapsed = compute_row_runtime(
        agent(status="DONE", start=start, run_start=None, stop=stop), now=now
    )
    assert ts == ("", "20:17:03")
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


@pytest.mark.parametrize(
    "status",
    ["PLAN APPROVED", "TALE APPROVED", "WORKING PLAN", "WORKING TALE"],
)
def test_compute_row_runtime_plan_handoff_linked_coder_child_returns_elapsed(
    status: str,
) -> None:
    start = datetime(2026, 5, 22, 18, 38, 12)
    run_start = datetime(2026, 5, 22, 18, 38, 39)
    child = agent(
        status=status,
        start=start,
        run_start=run_start,
        role_suffix="-code",
        raw_suffix="20260522143839",
        cl_name="a1y.f1-code",
    )
    child.parent_timestamp = "20260522143536"

    ts, elapsed = compute_row_runtime(
        child,
        now=datetime(2026, 5, 22, 18, 41, 5),
    )

    assert ts is None
    assert elapsed == "2m26s"
    assert runtime_suffix_ticks(child) is True


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


def test_compute_row_runtime_standalone_coder_active() -> None:
    from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX

    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 2, 5)
    coder = agent(
        start=start,
        status="TALE APPROVED",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    # The parent_workflow is None by default in agent()

    ts, elapsed = compute_row_runtime(coder, now=now)
    assert ts is None
    assert elapsed == "2m05s"
    assert runtime_suffix_ticks(coder, set()) is True


def test_compute_row_runtime_standalone_coder_continuation_active() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 2, 5)
    coder = agent(
        start=start,
        status="TALE APPROVED",
        role_suffix="--1",
    )
    coder.agent_family_role = "code"

    ts, elapsed = compute_row_runtime(coder, now=now)
    assert ts is None
    assert elapsed == "2m05s"
    assert runtime_suffix_ticks(coder, set()) is True


def test_compute_leaf_row_runtime_ignores_descendant_aggregation() -> None:
    start = datetime(2026, 4, 25, 13, 0, 0)
    run_start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 5, 0)
    parent = agent(start=start, run_start=run_start)
    parent.runtime_children.append(
        agent(
            start=datetime(2026, 4, 25, 14, 3, 0),
            run_start=datetime(2026, 4, 25, 14, 3, 0),
            raw_suffix="20260425140300",
            cl_name="child",
        )
    )
    childless_parent = agent(start=start, run_start=run_start)

    assert compute_row_runtime(parent, now=now) == (None, "2m")
    assert compute_leaf_row_runtime(parent, now=now) == compute_row_runtime(
        childless_parent,
        now=now,
    )
    assert compute_leaf_row_runtime(parent, now=now) == (None, "5m")


def test_compute_row_runtime_settled_starter_ignores_running_monitor() -> None:
    start = datetime(2026, 4, 25, 14, 30, 0)
    stop = datetime(2026, 4, 25, 14, 35, 0)
    now = datetime(2026, 4, 25, 14, 40, 0)
    starter = agent(
        status="DONE",
        start=start,
        stop=stop,
        cl_name="demo--code",
        role_suffix="--code",
    )
    starter.runtime_children.append(
        monitor_shell(start=datetime(2026, 4, 25, 14, 34, 0))
    )

    expected = compute_leaf_row_runtime(starter, now=now)
    assert compute_row_runtime(starter, now=now) == expected
    assert expected == (("", "14:35:00"), "5m")
    assert runtime_suffix_ticks(starter) is False


def test_compute_row_runtime_settled_starter_ignores_settled_monitor() -> None:
    start = datetime(2026, 4, 25, 14, 30, 0)
    stop = datetime(2026, 4, 25, 14, 35, 0)
    now = datetime(2026, 4, 25, 14, 50, 0)
    starter = agent(
        status="DONE",
        start=start,
        stop=stop,
        cl_name="demo--code",
        role_suffix="--code",
    )
    starter.runtime_children.append(
        monitor_shell(
            status="DONE",
            start=datetime(2026, 4, 25, 14, 34, 0),
            stop=datetime(2026, 4, 25, 14, 42, 0),
            monitor_state="completed",
        )
    )

    expected = compute_leaf_row_runtime(starter, now=now)
    assert compute_row_runtime(starter, now=now) == expected
    assert expected == (("", "14:35:00"), "5m")


def test_compute_row_runtime_family_container_spans_running_monitor() -> None:
    now = datetime(2026, 4, 25, 14, 40, 0)
    starter = agent(
        status="DONE",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=datetime(2026, 4, 25, 14, 35, 0),
        cl_name="demo--code",
        role_suffix="--code",
        raw_suffix="20260425143100",
    )
    starter.runtime_children.append(
        monitor_shell(start=datetime(2026, 4, 25, 14, 34, 0))
    )
    container = family_container(starter)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert ts is None
    assert elapsed == "6m"
    assert runtime_suffix_ticks(container) is True


def _planner_and_pending_gate() -> tuple[Agent, Agent]:
    planner = agent(
        status="DONE",
        start=datetime(2026, 4, 25, 14, 0, 0),
        stop=datetime(2026, 4, 25, 14, 30, 0),
        cl_name="demo--plan",
        role_suffix="--plan",
        raw_suffix="20260425140000",
    )
    gate = gate_shell(
        status="PLAN",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=None,
        gate_state="pending",
        raw_suffix="20260425143000",
    )
    return planner, gate


def test_family_container_excludes_pending_gate_review_window() -> None:
    planner, gate = _planner_and_pending_gate()
    container = family_container(planner)
    container.runtime_children.append(gate)
    container.followup_agents.append(gate)
    now = datetime(2026, 4, 25, 16, 0, 0)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert elapsed == "30m"
    assert ts == ("", "14:30:00")
    assert runtime_suffix_ticks(container) is False


def test_family_container_excludes_settled_gate_after_coder_starts() -> None:
    planner, _pending = _planner_and_pending_gate()
    gate = gate_shell(
        status="ANSWERED",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=datetime(2026, 4, 25, 16, 0, 0),
        gate_state="answered",
        raw_suffix="20260425143000",
    )
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 16, 0, 0),
        cl_name="demo--code",
        role_suffix="--code",
        raw_suffix="20260425160000",
    )
    container = family_container(planner)
    container.runtime_children.extend([gate, coder])
    container.followup_agents.extend([gate, coder])
    now = datetime(2026, 4, 25, 16, 10, 0)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert ts is None
    assert elapsed == "40m"
    assert runtime_suffix_ticks(container) is True


def test_family_container_finish_timestamp_ignores_settled_gate() -> None:
    planner, _pending = _planner_and_pending_gate()
    gate = gate_shell(
        status="ANSWERED",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=datetime(2026, 4, 25, 16, 0, 0),
        gate_state="answered",
        raw_suffix="20260425143000",
    )
    container = family_container(planner)
    container.runtime_children.append(gate)
    container.followup_agents.append(gate)
    now = datetime(2026, 4, 25, 16, 5, 0)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert elapsed == "30m"
    assert ts == ("", "14:30:00")


def test_gate_shell_own_row_still_reports_leaf_runtime() -> None:
    gate = gate_shell(
        status="ANSWERED",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=datetime(2026, 4, 25, 16, 0, 0),
        gate_state="answered",
    )
    now = datetime(2026, 4, 25, 16, 5, 0)

    ts, elapsed = compute_leaf_row_runtime(gate, now=now)
    assert elapsed == "1h30m"
    assert ts == ("", "16:00:00")
    assert compute_row_runtime(gate, now=now) == (ts, elapsed)


def test_family_container_includes_agent_attached_beneath_gate() -> None:
    planner, gate = _planner_and_pending_gate()
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 16, 0, 0),
        cl_name="demo--code",
        role_suffix="--code",
        raw_suffix="20260425160000",
    )
    gate.runtime_children.append(coder)
    container = family_container(planner)
    container.runtime_children.append(gate)
    container.followup_agents.append(gate)
    now = datetime(2026, 4, 25, 16, 10, 0)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert ts is None
    assert elapsed == "40m"


def test_family_container_includes_monitor_but_not_gate() -> None:
    starter = agent(
        status="DONE",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=datetime(2026, 4, 25, 14, 35, 0),
        cl_name="demo--code",
        role_suffix="--code",
        raw_suffix="20260425143100",
    )
    starter.runtime_children.append(
        monitor_shell(start=datetime(2026, 4, 25, 14, 34, 0))
    )
    gate = gate_shell(
        status="PLAN",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=None,
        gate_state="pending",
        raw_suffix="20260425143000",
    )
    container = family_container(starter)
    container.runtime_children.append(gate)
    container.followup_agents.append(gate)
    now = datetime(2026, 4, 25, 14, 40, 0)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert ts is None
    assert elapsed == "6m"
    assert runtime_suffix_ticks(container) is True


def test_family_container_chained_gates_do_not_resurrect_intervals() -> None:
    planner, outer = _planner_and_pending_gate()
    inner = gate_shell(
        status="PLAN",
        start=datetime(2026, 4, 25, 14, 45, 0),
        stop=None,
        gate_state="pending",
        raw_suffix="20260425144500",
        cl_name="demo--gate-0",
    )
    outer.runtime_children.append(inner)
    container = family_container(planner)
    container.runtime_children.append(outer)
    container.followup_agents.extend([outer, inner])
    now = datetime(2026, 4, 25, 16, 0, 0)

    ts, elapsed = compute_row_runtime(container, now=now)
    assert elapsed == "30m"
    assert ts == ("", "14:30:00")


def test_lowest_row_runtime_drops_family_parked_on_pending_gate() -> None:
    planner, gate = _planner_and_pending_gate()
    container = family_container(planner)
    container.runtime_children.append(gate)
    container.followup_agents.append(gate)
    now = datetime(2026, 4, 25, 16, 0, 0)

    assert compute_lowest_row_runtime([container], now=now) is None

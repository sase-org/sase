"""Tests for plan-aware and aggregated agent row runtime calculation."""

from __future__ import annotations

from datetime import datetime

from sase.agent.status_buckets import FEEDBACK_STATUS
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent import compute_row_runtime
from sase.ace.tui.models.agent_time import runtime_suffix_ticks

from .agent_list_runtime_helpers import agent, workflow_child


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


def test_compute_row_runtime_plan_done_row_uses_plan_time_before_stop_time() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    code = datetime(2026, 5, 6, 13, 15, 10)
    stop = datetime(2026, 5, 6, 13, 22, 40)
    now = datetime(2026, 5, 6, 13, 23, 0)

    ts, elapsed = compute_row_runtime(
        agent(
            status="PLAN DONE",
            start=start,
            stop=stop,
            plan_times=[datetime(2026, 5, 6, 13, 12, 0), plan],
            code_time=code,
            role_suffix=".plan",
        ),
        now=now,
    )

    assert ts == ("", "13:14:53")
    assert elapsed == "5m53s"


def test_compute_row_runtime_done_plan_step_prefers_plan_time_over_stop() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    code = datetime(2026, 5, 6, 13, 15, 10)
    stop = datetime(2026, 5, 6, 13, 22, 40)
    now = datetime(2026, 5, 6, 13, 23, 0)

    ts, elapsed = compute_row_runtime(
        workflow_child(
            step_type="agent",
            status="DONE",
            start=start,
            run_start=run_start,
            stop=stop,
            plan_times=[datetime(2026, 5, 6, 13, 12, 0), plan],
            code_time=code,
            cl_name="plan",
            role_suffix=".plan",
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


def test_compute_row_runtime_plan_approved_with_plan_times_is_frozen() -> None:
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

    assert ts == ("", "13:16:00")
    assert elapsed == "5m53s"


def test_plan_approved_plan_suffix_runtime_is_frozen() -> None:
    start = datetime(2026, 5, 6, 13, 9, 0)
    run_start = datetime(2026, 5, 6, 13, 10, 7)
    plan = datetime(2026, 5, 6, 13, 14, 53)
    code = datetime(2026, 5, 6, 13, 15, 10)
    now = datetime(2026, 5, 6, 13, 16, 15)

    result = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLAN APPROVED",
        start=start,
        run_start=run_start,
        plan_times=[plan],
        code_time=code,
        role_suffix=".plan",
    )

    ts, elapsed = compute_row_runtime(result, now=now)

    assert ts == ("", "13:14:53")
    assert elapsed == "4m46s"
    assert runtime_suffix_ticks(result) is False


def test_feedback_runtime_uses_plan_submission_before_feedback() -> None:
    start = datetime(2026, 6, 28, 13, 17, 57)
    p1 = datetime(2026, 6, 28, 13, 29, 35)
    f1 = datetime(2026, 6, 28, 13, 36, 5)
    p2 = datetime(2026, 6, 28, 13, 47, 25)
    result = agent(
        agent_type=AgentType.WORKFLOW,
        status=FEEDBACK_STATUS,
        start=start,
        run_start=start,
        plan_times=[p1, p2],
        role_suffix="--plan",
    )
    result.feedback_times = [f1]

    ts, elapsed = compute_row_runtime(result, now=datetime(2026, 6, 28, 13, 50, 0))

    assert ts == ("", "13:29:35")
    assert elapsed == "11m38s"
    assert runtime_suffix_ticks(result) is False


def test_compute_row_runtime_planning_parent_with_completed_child_is_stable() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="PLAN",
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
        status="PLAN",
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


def test_active_planner_workflow_child_does_not_freeze_at_plan_time() -> None:
    start = datetime(2026, 5, 21, 14, 49, 20)
    plan_submit = datetime(2026, 5, 21, 14, 52, 0)
    now = datetime(2026, 5, 21, 14, 55, 47)
    child = workflow_child(
        step_type="agent",
        status="RUNNING",
        start=start,
        run_start=start,
        plan_times=[plan_submit],
        cl_name="plan",
    )

    ts, elapsed = compute_row_runtime(child, now=now)

    assert ts is None
    assert elapsed == "6m27s"
    assert runtime_suffix_ticks(child) is True


def test_completed_planner_workflow_child_still_freezes_at_plan_time() -> None:
    start = datetime(2026, 5, 21, 14, 49, 20)
    run_start = datetime(2026, 5, 21, 14, 49, 30)
    plan_submit = datetime(2026, 5, 21, 14, 52, 0)
    now = datetime(2026, 5, 21, 14, 55, 47)
    child = workflow_child(
        step_type="agent",
        status="PLAN DONE",
        start=start,
        run_start=run_start,
        plan_times=[plan_submit],
        cl_name="plan",
    )

    ts, elapsed = compute_row_runtime(child, now=now)

    assert ts == ("", "14:52:00")
    assert elapsed == "2m30s"
    assert runtime_suffix_ticks(child) is False


def test_workflow_coder_child_with_tale_approved_ticks_from_run_start() -> None:
    start = datetime(2026, 5, 21, 15, 6, 0)
    run_start = datetime(2026, 5, 21, 15, 6, 24)
    now = datetime(2026, 5, 21, 15, 7, 54)
    child = workflow_child(
        step_type="agent",
        status="TALE APPROVED",
        start=start,
        run_start=run_start,
        cl_name="code",
    )

    ts, elapsed = compute_row_runtime(child, now=now)

    assert ts is None
    assert elapsed == "1m30s"
    assert runtime_suffix_ticks(child) is True


def test_sticky_approved_plan_workflow_child_freezes_at_plan_time() -> None:
    plan_start = datetime(2026, 5, 21, 14, 49, 20)
    plan_submit = datetime(2026, 5, 21, 14, 52, 0)
    now1 = datetime(2026, 5, 21, 14, 56, 50)
    now2 = datetime(2026, 5, 21, 14, 56, 51)
    child = workflow_child(
        step_type="agent",
        status="TALE APPROVED",
        start=plan_start,
        run_start=plan_start,
        plan_times=[plan_submit],
        cl_name="plan",
        role_suffix=".plan",
    )

    ts1, elapsed1 = compute_row_runtime(child, now=now1)
    ts2, elapsed2 = compute_row_runtime(child, now=now2)

    assert ts1 == ("", "14:52:00")
    assert elapsed1 == "2m40s"
    assert ts2 == ("", "14:52:00")
    assert elapsed2 == "2m40s"
    assert runtime_suffix_ticks(child) is False


def test_question_continuation_planner_approved_runtime_freezes() -> None:
    start = datetime(2026, 6, 23, 7, 5, 50)
    plan_submit = datetime(2026, 6, 23, 7, 6, 42)
    child = agent(
        status="TALE APPROVED",
        start=start,
        run_start=start,
        plan_times=[plan_submit],
        role_suffix="--plan",
        raw_suffix="20260623070550",
    )
    child.parent_timestamp = "20260623065702"
    child.agent_family_role = "q"

    ts, elapsed = compute_row_runtime(child, now=datetime(2026, 6, 23, 7, 33, 38))

    assert ts == ("", "07:06:42")
    assert elapsed == "52s"
    assert runtime_suffix_ticks(child) is False


def test_workflow_root_aggregate_ticks_at_1s_per_1s_with_done_plan_child() -> None:
    """Regression: a DONE plan child + RUNNING epic child must tick 1s/1s.

    The original bug aggregated two active intervals (each ticking 1s/s)
    when the planner's marker was stuck at RUNNING, so the root suffix
    ticked at 2s/1s. Once the data/TUI fix freezes the plan child at
    plan_times, the root aggregate equals the (frozen) plan elapsed plus
    the (live) epic elapsed and only the epic child contributes new
    seconds.
    """
    plan_start = datetime(2026, 5, 21, 14, 49, 20)
    plan_submit = datetime(2026, 5, 21, 14, 52, 0)
    epic_start = datetime(2026, 5, 21, 15, 6, 0)

    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="EPIC APPROVED",
        start=plan_start,
        run_start=plan_start,
    )
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=plan_start,
        run_start=plan_start,
        plan_times=[plan_submit],
        cl_name="plan",
        role_suffix=".plan",
    )
    epic = workflow_child(
        step_type="agent",
        status="RUNNING",
        start=epic_start,
        run_start=epic_start,
        raw_suffix="20260521150600",
        cl_name="epic",
    )
    parent.runtime_children.extend([planner, epic])

    now1 = datetime(2026, 5, 21, 15, 7, 0)
    now2 = datetime(2026, 5, 21, 15, 7, 1)
    _, elapsed1 = compute_row_runtime(parent, now=now1)
    _, elapsed2 = compute_row_runtime(parent, now=now2)

    # planner is frozen at plan_submit (2m40s) -> contributes a constant
    # value. epic ticks live (1m -> 1m01s). The root therefore advances
    # by exactly one second between now1 and now2 — not two.
    assert elapsed1 == "3m40s"
    assert elapsed2 == "3m41s"
    assert runtime_suffix_ticks(parent) is True


def test_workflow_root_aggregate_ticks_at_1s_per_1s_with_approved_plan_child() -> None:
    plan_start = datetime(2026, 5, 21, 14, 49, 20)
    plan_submit = datetime(2026, 5, 21, 14, 52, 0)
    code_start = datetime(2026, 5, 21, 15, 6, 0)

    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="WORKING TALE",
        start=plan_start,
        run_start=plan_start,
    )
    planner = workflow_child(
        step_type="agent",
        status="TALE APPROVED",
        start=plan_start,
        run_start=plan_start,
        plan_times=[plan_submit],
        cl_name="plan",
        role_suffix=".plan",
    )
    coder = workflow_child(
        step_type="agent",
        status="WORKING TALE",
        start=code_start,
        run_start=code_start,
        raw_suffix="20260521150600",
        cl_name="code",
    )
    parent.runtime_children.extend([planner, coder])

    now1 = datetime(2026, 5, 21, 15, 7, 0)
    now2 = datetime(2026, 5, 21, 15, 7, 1)
    _, elapsed1 = compute_row_runtime(parent, now=now1)
    _, elapsed2 = compute_row_runtime(parent, now=now2)

    assert elapsed1 == "3m40s"
    assert elapsed2 == "3m41s"
    assert runtime_suffix_ticks(parent) is True


def test_workflow_root_aggregates_active_plan_and_code_children() -> None:
    plan_start = datetime(2026, 5, 21, 14, 49, 20)
    plan_submit = datetime(2026, 5, 21, 14, 52, 0)
    code_start = datetime(2026, 5, 21, 15, 6, 24)
    now = datetime(2026, 5, 21, 15, 7, 54)

    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="TALE APPROVED",
        start=plan_start,
        run_start=plan_start,
    )
    planner = workflow_child(
        step_type="agent",
        status="RUNNING",
        start=plan_start,
        run_start=plan_start,
        plan_times=[plan_submit],
        cl_name="plan",
    )
    coder = workflow_child(
        step_type="agent",
        status="TALE APPROVED",
        start=code_start,
        run_start=code_start,
        raw_suffix="20260521150624",
        cl_name="code",
    )
    parent.runtime_children.extend([planner, coder])

    ts, elapsed = compute_row_runtime(parent, now=now)

    assert ts is None
    # The core interval union excludes the plan-review pause between the
    # planner submission and code launch instead of charging it as runtime.
    assert elapsed == "4m10s"
    assert runtime_suffix_ticks(parent) is True

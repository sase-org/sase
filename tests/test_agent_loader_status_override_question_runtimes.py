"""Tests for question-continuation runtime status overrides."""

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType, compute_row_runtime
from sase.ace.tui.models.agent_time import runtime_suffix_ticks
from sase.ace.tui.models.agent_loader import _apply_status_overrides


@pytest.mark.parametrize(
    ("plan_action", "expected_status"),
    [("tale", "TALE APPROVED"), ("approve", "PLAN APPROVED")],
)
def test_apply_status_overrides_question_continuation_inner_approver_runtime(
    plan_action: str,
    expected_status: str,
) -> None:
    """The visible continuation row aggregates its inner main step runtime."""
    question_time = datetime(2026, 6, 23, 7, 5, 49)
    continuation_start = datetime(2026, 6, 23, 7, 5, 50)
    plan_time = datetime(2026, 6, 23, 7, 6, 42)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 6, 57, 2),
        raw_suffix="20260623065702",
        role_suffix="--0",
        agent_name="sase-03w",
        agent_family="sase-03w",
        agent_family_role="root",
        plan_chain_root=True,
        questions_times=[question_time],
    )
    continuation = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=continuation_start,
        run_start_time=continuation_start,
        raw_suffix="20260623070550",
        parent_timestamp=parent.raw_suffix,
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="agent",
        questions_times=[question_time],
        plan_times=[plan_time],
        plan_action=plan_action,
    )
    inner_main_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=continuation_start,
        run_start_time=continuation_start,
        raw_suffix=continuation.raw_suffix,
        parent_workflow="ace-run",
        parent_timestamp=continuation.raw_suffix,
        step_type="agent",
        role_suffix="--plan",
        agent_name="sase-03w--1",
        agent_family="sase-03w",
        agent_family_role="agent",
        questions_times=[question_time],
        plan_times=[plan_time],
        plan_action=plan_action,
    )
    continuation.runtime_children.append(inner_main_step)

    _apply_status_overrides([parent, continuation], [inner_main_step])

    assert continuation.status == expected_status
    assert inner_main_step.status == expected_status
    assert compute_row_runtime(continuation, now=datetime(2026, 6, 23, 7, 33, 38)) == (
        ("", "07:06:42"),
        "52s",
    )
    assert runtime_suffix_ticks(continuation) is False

"""Tests for runtime suffix ticking decisions."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent_time import runtime_suffix_ticks

from .agent_list_runtime_helpers import (
    agent,
    linked_followup_workflow,
    workflow_child,
)


@pytest.mark.parametrize("status", ["PLAN APPROVED", "LEGEND APPROVED"])
def test_runtime_suffix_ticks_parent_status_alone_is_stable(status: str) -> None:
    result = agent(status=status)
    assert runtime_suffix_ticks(result) is False


def test_runtime_suffix_ticks_plan_approved_with_plan_times_is_frozen() -> None:
    result = agent(
        status="PLAN APPROVED",
        plan_times=[datetime(2026, 5, 6, 13, 14, 53)],
        code_time=datetime(2026, 5, 6, 13, 15, 10),
    )
    assert runtime_suffix_ticks(result) is False


def test_runtime_suffix_ticks_parent_with_active_runtime_child() -> None:
    parent = agent(status="PLAN")
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

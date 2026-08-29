"""Tests for runtime suffix ticking decisions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_time import (
    row_runtime_or_wait_ticks,
    runtime_suffix_ticks,
    wait_countdown_ticks,
    wait_remaining_seconds,
)

from .agent_list_runtime_helpers import (
    agent,
    family_container,
    gate_shell,
    linked_followup_workflow,
    monitor_shell,
    workflow_child,
)

_TICK_DECISIONS: tuple[Callable[[Agent], bool], ...] = (
    runtime_suffix_ticks,
    row_runtime_or_wait_ticks,
)


@pytest.mark.parametrize("status", ["PLAN APPROVED"])
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


def test_runtime_suffix_ticks_live_monitor_custom_status() -> None:
    result = agent(status="MONITORING")
    result.agent_family_role = "monitor"
    result.role_suffix = "--mon"
    result.monitor_id = "m123"
    result.monitor_state = "running"

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


@pytest.mark.parametrize("ticks", _TICK_DECISIONS)
def test_settled_starter_with_running_monitor_does_not_tick(
    ticks: Callable[[Agent], bool],
) -> None:
    starter = agent(
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 35, 0),
        cl_name="demo--code",
        role_suffix="--code",
    )
    child = monitor_shell()
    starter.runtime_children.append(child)

    assert ticks(starter) is False
    assert ticks(child) is True


@pytest.mark.parametrize("ticks", _TICK_DECISIONS)
def test_family_container_ticks_through_settled_starter_to_monitor(
    ticks: Callable[[Agent], bool],
) -> None:
    starter = agent(
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 35, 0),
        cl_name="demo--code",
        role_suffix="--code",
        raw_suffix="20260425143100",
    )
    starter.runtime_children.append(monitor_shell())
    container = family_container(starter)

    assert container.is_family_container_row is True
    assert ticks(container) is True
    assert ticks(starter) is False


@pytest.mark.parametrize("ticks", _TICK_DECISIONS)
def test_clan_container_ticks_with_running_monitor_descendant(
    ticks: Callable[[Agent], bool],
) -> None:
    starter = agent(
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 35, 0),
        cl_name="demo--code",
        role_suffix="--code",
        raw_suffix="20260425143100",
    )
    starter.runtime_children.append(monitor_shell())
    clan = agent(status="DONE", stop=datetime(2026, 4, 25, 14, 35, 0), cl_name="clan")
    clan.is_clan_container = True
    clan.runtime_children.append(starter)

    assert ticks(clan) is True
    assert ticks(starter) is False


@pytest.mark.parametrize("ticks", _TICK_DECISIONS)
def test_settled_starter_with_running_non_monitor_child_still_ticks(
    ticks: Callable[[Agent], bool],
) -> None:
    starter = agent(
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 35, 0),
        cl_name="demo--code",
        role_suffix="--code",
    )
    starter.runtime_children.append(
        agent(status="RUNNING", raw_suffix="20260425143100", cl_name="child")
    )

    assert ticks(starter) is True


@pytest.mark.parametrize("ticks", _TICK_DECISIONS)
@pytest.mark.parametrize("gate_state", ["pending", "settling"])
def test_family_container_does_not_tick_for_gate(
    ticks: Callable[[Agent], bool],
    gate_state: str,
) -> None:
    planner = agent(
        status="DONE",
        stop=datetime(2026, 4, 25, 14, 30, 0),
        cl_name="demo--plan",
        role_suffix="--plan",
        raw_suffix="20260425140000",
    )
    gate = gate_shell(
        status="PLAN",
        start=datetime(2026, 4, 25, 14, 30, 0),
        stop=None,
        gate_state=gate_state,
    )
    container = family_container(planner)
    container.runtime_children.append(gate)
    container.followup_agents.append(gate)

    assert ticks(container) is False


@pytest.mark.parametrize("ticks", _TICK_DECISIONS)
def test_gate_row_ticks_while_settling_not_pending(
    ticks: Callable[[Agent], bool],
) -> None:
    pending = gate_shell(status="PLAN", gate_state="pending")
    settling = gate_shell(status="PLAN", gate_state="settling")

    assert ticks(pending) is False
    assert ticks(settling) is True


def test_wait_countdown_ticks_waiting_with_wait_until() -> None:
    result = agent(
        status="WAITING",
        run_start=None,
    )
    result.wait_until = "2026-04-25T14:35:00"

    assert runtime_suffix_ticks(result) is False
    assert wait_countdown_ticks(result) is True
    assert row_runtime_or_wait_ticks(result) is True


def test_wait_countdown_ticks_waiting_with_relative_time_floor() -> None:
    result = agent(
        status="WAITING",
        run_start=None,
    )
    result.wait_duration = 300.0

    assert runtime_suffix_ticks(result) is False
    assert wait_countdown_ticks(result) is True
    assert row_runtime_or_wait_ticks(result) is True


def test_wait_countdown_waits_for_authoritative_post_dependency_deadline() -> None:
    result = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 30, 0),
        run_start=None,
    )
    result.waiting_for = ["dep"]
    result.wait_duration = 300.0

    assert (
        wait_remaining_seconds(
            result,
            now=datetime(2026, 4, 25, 14, 31, 0),
        )
        is None
    )
    assert wait_countdown_ticks(result) is False
    assert row_runtime_or_wait_ticks(result) is False


def test_wait_countdown_ticks_after_post_dependency_deadline_is_written() -> None:
    result = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 30, 0),
        run_start=None,
    )
    result.waiting_for = ["dep"]
    result.wait_duration = 300.0
    result.wait_until = "2026-04-25T14:40:00"

    assert (
        wait_remaining_seconds(
            result,
            now=datetime(2026, 4, 25, 14, 38, 30),
        )
        == 90.0
    )
    assert wait_countdown_ticks(result) is True
    assert row_runtime_or_wait_ticks(result) is True


def test_wait_countdown_ticks_skips_plain_waiting_and_non_waiting() -> None:
    plain_waiting = agent(status="WAITING", run_start=None)
    running = agent(status="RUNNING")
    running.wait_until = "2026-04-25T14:35:00"

    assert wait_countdown_ticks(plain_waiting) is False
    assert row_runtime_or_wait_ticks(plain_waiting) is False
    assert wait_countdown_ticks(running) is False


def test_wait_display_source_waits_for_authoritative_dependency_deadline() -> None:
    root = agent(status="WAITING", run_start=None)
    child = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 30, 0),
        run_start=None,
        raw_suffix="20260425143100",
        cl_name="child",
    )
    child.waiting_for = ["dep"]
    child.wait_duration = 300.0
    root.wait_display_source = child

    assert (
        wait_remaining_seconds(
            root,
            now=datetime(2026, 4, 25, 14, 31, 0),
        )
        is None
    )
    assert wait_countdown_ticks(root) is False
    assert row_runtime_or_wait_ticks(root) is False


def test_wait_display_source_uses_child_wait_until_countdown() -> None:
    root = agent(status="WAITING", run_start=None)
    child = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 30, 0),
        run_start=None,
        raw_suffix="20260425143100",
        cl_name="child",
    )
    child.waiting_for = ["dep"]
    child.wait_duration = 300.0
    child.wait_until = "2026-04-25T14:40:00"
    root.wait_display_source = child

    assert (
        wait_remaining_seconds(
            root,
            now=datetime(2026, 4, 25, 14, 38, 30),
        )
        == 90.0
    )
    assert wait_countdown_ticks(root) is True
    assert row_runtime_or_wait_ticks(root) is True


def test_wait_display_source_uses_child_duration_countdown() -> None:
    root = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        run_start=None,
    )
    child = agent(
        status="WAITING",
        start=datetime(2026, 4, 25, 14, 30, 0),
        run_start=None,
        raw_suffix="20260425143100",
        cl_name="child",
    )
    child.wait_duration = 300.0
    root.wait_display_source = child

    assert (
        wait_remaining_seconds(
            root,
            now=datetime(2026, 4, 25, 14, 31, 0),
        )
        == 240.0
    )
    assert wait_countdown_ticks(root) is True
    assert row_runtime_or_wait_ticks(root) is True

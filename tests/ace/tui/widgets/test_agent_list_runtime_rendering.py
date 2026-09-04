"""Tests for AgentList live and family runtime suffix rendering."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option

from .agent_list_runtime_helpers import agent, workflow_child


def test_format_agent_option_active_suffix_contains_only_elapsed() -> None:
    start = datetime(2026, 4, 25, 14, 0, 0)
    now = datetime(2026, 4, 25, 14, 38, 45)
    _, suffix, _ = format_agent_option(
        agent(start=start), 0, is_selected=False, now=now
    )
    assert suffix.plain == "🏃‍♂️ 38m45s"


@pytest.mark.parametrize(
    ("runtime_agent", "expected"),
    [
        (
            agent(
                status="WAITING",
                start=datetime(2026, 4, 25, 13, 0, 0),
                run_start=datetime(2026, 4, 25, 14, 0, 0),
            ),
            "🏃‍♂️ 5m",
        ),
        (
            agent(
                status="RETRYING",
                start=datetime(2026, 4, 25, 14, 4, 48),
            ),
            "🏃‍♂️ 12s",
        ),
        (
            workflow_child(
                step_type="agent",
                status="RUNNING",
                start=datetime(2026, 4, 25, 14, 2, 55),
            ),
            "🏃‍♂️ 2m05s",
        ),
    ],
)
def test_format_agent_option_live_suffix_has_runtime_marker(
    runtime_agent: Agent, expected: str
) -> None:
    now = datetime(2026, 4, 25, 14, 5, 0)
    _, suffix, _ = format_agent_option(runtime_agent, 0, is_selected=False, now=now)
    assert suffix.plain == expected


def test_format_agent_option_aggregate_parent_uses_interval_union() -> None:
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

    _, suffix, _ = format_agent_option(
        parent,
        0,
        is_selected=False,
        now=datetime(2026, 5, 6, 13, 16, 15),
    )

    assert suffix.plain == "🏃‍♂️ 6m01s"


def test_format_agent_option_aggregate_parent_does_not_double_count_overlap() -> None:
    parent = agent(
        agent_type=AgentType.WORKFLOW,
        status="DONE",
        start=datetime(2026, 7, 17, 10, 0, 0),
    )
    first = agent(
        status="DONE",
        start=datetime(2026, 7, 17, 10, 0, 0),
        run_start=datetime(2026, 7, 17, 10, 0, 0),
        stop=datetime(2026, 7, 17, 10, 10, 0),
        raw_suffix="first",
    )
    second = agent(
        status="DONE",
        start=datetime(2026, 7, 17, 10, 5, 0),
        run_start=datetime(2026, 7, 17, 10, 5, 0),
        stop=datetime(2026, 7, 17, 10, 15, 0),
        raw_suffix="second",
    )
    parent.runtime_children.extend([first, second])

    _, suffix, _ = format_agent_option(
        parent,
        0,
        is_selected=False,
        now=datetime(2026, 7, 17, 10, 20, 0),
    )

    assert suffix.plain == "10:15:00 · 15m"


def test_format_agent_option_active_family_shows_current_root_and_total() -> None:
    root = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="root",
        cl_name="family",
    )
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    root.role_suffix = "--0"
    waiting_child = agent(
        status="WAITING",
        start=datetime(2026, 7, 19, 9, 1, 0),
        run_start=None,
        raw_suffix="waiting",
        cl_name="family--review",
    )
    waiting_child.parent_timestamp = root.raw_suffix
    waiting_child.agent_family = "family"
    waiting_child.agent_family_role = "review"
    waiting_child.role_suffix = "--review"
    root.followup_agents = [waiting_child]

    _, suffix, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 3, 5),
    )

    assert suffix.plain == "🏃‍♂️ 3m05s / 3m05s"


def test_format_agent_option_active_family_shows_current_continuation_first() -> None:
    root = agent(
        agent_type=AgentType.WORKFLOW,
        status="WORKING TALE",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix="root",
        cl_name="family-workflow",
    )
    root.agent_name = "family--plan"
    root.agent_family = "family"
    root.agent_family_role = "root"
    root.plan_chain_root = True
    planner = workflow_child(
        step_type="agent",
        status="DONE",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        plan_times=[datetime(2026, 7, 19, 9, 2, 0)],
        raw_suffix="planner",
        cl_name="plan",
    )
    coder = agent(
        status="RUNNING",
        start=datetime(2026, 7, 19, 9, 4, 0),
        run_start=datetime(2026, 7, 19, 9, 4, 0),
        raw_suffix="coder",
        cl_name="family--code",
    )
    coder.parent_timestamp = root.raw_suffix
    coder.agent_family = "family"
    coder.agent_family_role = "code"
    coder.role_suffix = "--code"
    root.runtime_children = [planner, coder]
    root.followup_agents = [coder]

    _, suffix, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 5, 5),
    )

    assert suffix.plain == "🏃‍♂️ 1m05s / 3m05s"


def test_format_agent_option_active_family_uses_nested_monitor_runtime() -> None:
    root = agent(
        status="DONE",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        stop=datetime(2026, 7, 19, 9, 1, 0),
        raw_suffix="root",
        cl_name="family",
    )
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    coder = agent(
        status="DONE",
        start=datetime(2026, 7, 19, 9, 1, 0),
        run_start=datetime(2026, 7, 19, 9, 1, 0),
        stop=datetime(2026, 7, 19, 9, 2, 0),
        raw_suffix="coder",
        cl_name="family--code",
    )
    coder.parent_timestamp = root.raw_suffix
    coder.agent_family = "family"
    coder.agent_family_role = "code"
    monitor = agent(
        status="MONITORING",
        start=datetime(2026, 7, 19, 9, 3, 0),
        run_start=datetime(2026, 7, 19, 9, 3, 0),
        raw_suffix="monitor",
        cl_name="family--mon",
    )
    monitor.parent_timestamp = coder.raw_suffix
    monitor.agent_family = "family"
    monitor.agent_family_role = "monitor"
    monitor.role_suffix = "--mon"
    monitor.monitor_id = "m-family"
    monitor.monitor_state = "running"
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]

    _, suffix, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 5, 0),
    )

    assert suffix.plain == "🏃‍♂️ 2m / 3m"


def test_format_agent_option_completed_family_keeps_single_total_suffix() -> None:
    root = agent(
        status="DONE",
        start=datetime(2026, 7, 19, 9, 0, 0),
        run_start=datetime(2026, 7, 19, 9, 0, 0),
        stop=datetime(2026, 7, 19, 9, 1, 0),
        raw_suffix="root",
        cl_name="family",
    )
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    child = agent(
        status="DONE",
        start=datetime(2026, 7, 19, 9, 1, 0),
        run_start=datetime(2026, 7, 19, 9, 1, 0),
        stop=datetime(2026, 7, 19, 9, 2, 0),
        raw_suffix="child",
        cl_name="family--code",
    )
    child.parent_timestamp = root.raw_suffix
    child.agent_family = "family"
    child.agent_family_role = "code"
    root.runtime_children = [child]
    root.followup_agents = [child]

    _, suffix, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        now=datetime(2026, 7, 19, 9, 3, 0),
    )

    assert suffix.plain == "09:02:00 · 1m"
    assert " / " not in suffix.plain

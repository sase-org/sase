"""Tests for monitor-row render keys and container cache invalidation."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import (
    AgentRenderCache,
    agent_render_key,
    cached_format_agent_option,
)
from sase.ace.tui.widgets._agent_list_styling import (
    _MONITOR_COUNT_GLYPH_STYLE,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
)

from ._agent_render_cache_helpers import style_at as _style_at


def _family_container_with_running_monitor() -> tuple[Agent, Agent]:
    started = datetime(2026, 4, 25, 14, 30, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-root",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260425143000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="20260425143001",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state="running",
        monitor_label="just check",
    )
    root.followup_agents = [monitor]
    return root, monitor


def _monitor_row_render_key(
    *,
    monitor_state: str,
    stop_time: datetime | None,
) -> tuple[object, ...]:
    started = datetime(2026, 4, 25, 14, 30, 0)
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon",
        project_file="/tmp/monitor.sase",
        status="MONITORING" if stop_time is None else "MONITORED",
        start_time=started,
        stop_time=stop_time,
        raw_suffix="20260425143001",
        parent_timestamp="20260425143000",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state=monitor_state,
        monitor_label="just check",
    )
    return agent_render_key(
        monitor,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
    )


def test_agent_render_key_differs_when_monitor_pair_changes() -> None:
    started = datetime(2026, 4, 25, 14, 30, 0)
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon",
        project_file="/tmp/monitor.sase",
        status="TESTING",
        start_time=started,
        raw_suffix="20260425143001",
        parent_timestamp="20260425143000",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state="running",
        monitor_label="just check",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
    )
    before = agent_render_key(
        monitor,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
    )
    monitor.monitor_start_status = "SLEEPING"
    monitor.monitor_stop_status = "SLEPT"
    monitor.status = "SLEEPING"
    after = agent_render_key(
        monitor,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
    )

    assert before != after


def test_agent_render_key_differs_for_running_and_settled_monitor_rows() -> None:
    running_key = _monitor_row_render_key(monitor_state="running", stop_time=None)
    settled_key = _monitor_row_render_key(
        monitor_state="completed",
        stop_time=datetime(2026, 4, 25, 14, 33, 0),
    )

    assert running_key != settled_key


def test_cached_container_row_invalidates_when_monitor_settles() -> None:
    cache = AgentRenderCache()
    root, monitor = _family_container_with_running_monitor()

    running_parts = cached_format_agent_option(
        cache, root, 0, is_selected=False, now=None
    )
    monitor.monitor_state = "completed"
    monitor.stop_time = datetime(2026, 4, 25, 14, 33, 0)
    settled_parts = cached_format_agent_option(
        cache, root, 0, is_selected=False, now=None
    )

    assert running_parts[0] is not settled_parts[0]
    running_index = running_parts[0].plain.index("⚙1")
    assert _style_at(running_parts[0], running_index) == _MONITOR_COUNT_GLYPH_STYLE
    settled_index = settled_parts[0].plain.index("⚙1")
    assert (
        _style_at(settled_parts[0], settled_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE
    )


def test_cached_container_row_invalidates_when_settled_monitor_arrives() -> None:
    """The settled lane must be a cache-key input on its own.

    A second monitor arriving already settled leaves the running lane
    unchanged (still 1) while the settled lane moves 0 -> 1. If the settled
    count were left out of ``agent_render_key``, this render would
    incorrectly reuse the stale cached entry.
    """
    cache = AgentRenderCache()
    root, running_monitor = _family_container_with_running_monitor()

    before = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)
    assert before[0].plain.count("⚙1") == 1

    arrived_settled = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon-2",
        project_file="/tmp/monitor.sase",
        status="MONITORED",
        start_time=datetime(2026, 4, 25, 14, 30, 0),
        stop_time=datetime(2026, 4, 25, 14, 33, 0),
        raw_suffix="20260425143002",
        parent_timestamp=root.raw_suffix,
        agent_name="alpha--mon-2",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon-2",
        monitor_id="m2",
        monitor_state="completed",
        monitor_label="just check",
    )
    root.followup_agents = [running_monitor, arrived_settled]
    after = cached_format_agent_option(cache, root, 0, is_selected=False, now=None)

    assert before[0] is not after[0]
    assert "⚙1 ⚙1" in after[0].plain

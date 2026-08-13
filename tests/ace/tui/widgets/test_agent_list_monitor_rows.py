"""Monitor member row rendering tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option


def _monitor(
    *,
    status: str,
    monitor_state: str,
    exit_code: int | None = None,
) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    stop_time = (
        started + timedelta(minutes=3)
        if monitor_state in {"completed", "failed", "timeout", "stopped", "lost"}
        else None
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status=status,
        status_bucket=(
            "Running"
            if monitor_state == "running"
            else "Failed"
            if monitor_state in {"failed", "timeout", "lost"}
            else "Done"
        ),
        start_time=started,
        run_start_time=started,
        stop_time=stop_time,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m123",
        monitor_state=monitor_state,
        monitor_label="just check",
        monitor_command="just check-full",
        monitor_exit_code=exit_code,
    )


def test_monitor_row_uses_glyph_and_label_without_the_command() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert "⏱" in left.plain
    assert "just check" in left.plain
    assert "just check-full" not in left.plain
    assert "MONITORING" in left.plain


def test_failed_monitor_row_renders_exit_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="failed", exit_code=1),
        0,
        is_selected=False,
    )

    assert "✗ 1" in left.plain


def test_timeout_monitor_row_renders_timeout_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="timeout"),
        0,
        is_selected=False,
    )

    assert "⧖" in left.plain


def test_lost_monitor_row_renders_as_failed_without_exit_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="lost", exit_code=1),
        0,
        is_selected=False,
    )

    assert "MONITORED" in left.plain
    assert "✗ 1" not in left.plain

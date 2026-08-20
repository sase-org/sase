"""Shared fixtures for agent-list monitor row tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType


def make_monitor(
    *,
    status: str,
    monitor_state: str | None,
    exit_code: int | None = None,
    followup_error: str | None = None,
    followup_outcome: str | None = None,
    start_status: str | None = "MONITORING",
    stop_status: str | None = "MONITORED",
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
        monitor_start_status=start_status,
        monitor_stop_status=stop_status,
        monitor_exit_code=exit_code,
        monitor_followup_error=followup_error,
        monitor_followup_outcome=followup_outcome,
    )


def make_monitor_starter() -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="starter-row",
        project_file="/tmp/monitor.sase",
        status="DONE",
        status_bucket="Done",
        start_time=started,
        stop_time=started + timedelta(minutes=3),
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
        monitor_id="m123",
        monitor_label="just check",
        monitor_command="just check-full",
    )


def style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def gear_style(text: Text) -> str | None:
    return style_at(text, text.plain.index("⚙"))


def make_family_container(*monitor_states: str) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-root",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
    )
    monitors = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"alpha-mon-{index}",
            project_file="/tmp/monitor.sase",
            status="MONITORING" if monitor_state == "running" else "MONITORED",
            start_time=started,
            stop_time=None
            if monitor_state == "running"
            else started + timedelta(minutes=3),
            raw_suffix=f"2026081209000{index + 1}",
            parent_timestamp="20260812090000",
            agent_name=f"alpha--mon-{index}",
            agent_family="alpha",
            agent_family_role="monitor",
            role_suffix=f"--mon-{index}",
            monitor_id=f"m{index}",
            monitor_state=monitor_state,
            monitor_label="just check",
        )
        for index, monitor_state in enumerate(monitor_states)
    ]
    root.followup_agents = monitors
    return root

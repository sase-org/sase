"""Tasks tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

import pytest

from sase.ace.tui.modals import procs_pane_render as tpr
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.monitor_state import MONITOR_PROC_ORIGIN

_FIXED_TASK_NOW = datetime(2026, 6, 26, 12, 0, 0)
_RUNNING_MONITOR_PROC_ID = "mon-check-full"
_FINISHED_MONITOR_PROC_ID = "mon-pytest"


class _NoopProcObserver:
    def request_poll(self) -> None:
        return None

    def set_detail_proc(self, proc_id: str | None) -> None:
        del proc_id

    def stop(self, *, timeout: float = 1.0) -> None:
        del timeout


def _task(
    proc_id: str,
    *,
    label: str,
    status: str,
    age_seconds: int,
    output: str = "",
    error: str | None = None,
    live_output: str | None = None,
) -> ObservedProc:
    return _visual_task(
        proc_id,
        label=label,
        status=status,
        age_seconds=age_seconds,
        output=output,
        error=error,
        live_output=live_output,
    )


def _visual_task(
    proc_id: str,
    *,
    label: str,
    status: str,
    age_seconds: int,
    output: str = "",
    error: str | None = None,
    live_output: str | None = None,
    origin: str = "",
    shell_name: str | None = None,
    command: list[str] | None = None,
    message: str | None = None,
) -> ObservedProc:
    started_at = _FIXED_TASK_NOW.replace(tzinfo=None) - timedelta(seconds=age_seconds)
    info = ObservedProc(
        proc_id=proc_id,
        proc_type=label.split()[0],
        cl_name="",
        project_file="",
        status=status,
        message=message if message is not None else f"{label} complete",
        started_at=started_at,
        display_name=label,
        finished_at=started_at if status != "running" else None,
        output=output,
        error=error,
        origin=origin,
        shell_name=shell_name,
        command=command,
    )
    if live_output is not None:
        info._live_buffer = io.StringIO(live_output)
        info.output = live_output
    return info


def _running_monitor_row() -> ObservedProc:
    """Return a running monitor row with an orange gear, agent name, and tail."""
    return _visual_task(
        _RUNNING_MONITOR_PROC_ID,
        label="just check-full",
        status="running",
        age_seconds=12,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
        command=["/bin/sh", "-c", "just check-full"],
        live_output=(
            "ruff .................. Passed\n"
            "mypy ................... Passed\n"
            "pytest tests/ace ......\n"
        ),
    )


def _finished_monitor_row() -> ObservedProc:
    """Return a settled monitor row that still wears the orange gear."""
    return _visual_task(
        _FINISHED_MONITOR_PROC_ID,
        label="pytest -x",
        status="killed",
        age_seconds=14 * 60,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="hotfix--mon-0",
        command=["/bin/sh", "-c", "pytest -x"],
        message="Killed",
        output="collected 12 items\nF\n",
    )


def _monitor_visual_agent(*, monitor_id: str, presented_agent_name: str) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-monitor",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=None,
        monitor_id=monitor_id,
    )
    agent.presented_agent_name = presented_agent_name
    return agent


def _attach_monitor_visual_agents(app: Any) -> None:
    """Append the fixture monitor agents so names and ⏎: agent resolve."""
    extras = (
        _monitor_visual_agent(
            monitor_id=_RUNNING_MONITOR_PROC_ID,
            presented_agent_name="acme--mon",
        ),
        _monitor_visual_agent(
            monitor_id=_FINISHED_MONITOR_PROC_ID,
            presented_agent_name="hotfix--mon-0",
        ),
    )
    existing = list(getattr(app, "_agents", ()))
    existing.extend(extras)
    app._agents = existing


def _freeze_procs_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin relative times and the running spinner for byte-stable snapshots."""
    original_relative_time = tpr._relative_time
    monkeypatch.setattr(
        tpr,
        "_relative_time",
        lambda dt: original_relative_time(dt, now=_FIXED_TASK_NOW),
    )
    original_elapsed = tpr._elapsed
    monkeypatch.setattr(
        tpr,
        "_elapsed",
        lambda task, *, now=None: original_elapsed(
            task,
            now=_FIXED_TASK_NOW.replace(tzinfo=None),
        ),
    )
    # Freeze the running-task spinner so the status token is byte-stable; the
    # 0.25s refresh timer would otherwise advance it between runs.
    monkeypatch.setattr(tpr, "_SPINNER_FRAMES", ("|",))


def _seed_tasks_tab_queue(
    app: Any,
    *,
    extra_rows: tuple[ObservedProc, ...] = (),
) -> None:
    observer = getattr(app, "_proc_observer", None)
    stop = getattr(observer, "stop", None)
    if callable(stop):
        stop()
    app._proc_observer = _NoopProcObserver()
    rows = (
        _task(
            "sync",
            label="sync sase-42",
            status="running",
            age_seconds=3,
            live_output=(
                "Syncing sase-42...\n"
                "remote: Enumerating objects: 1240\n"
                "remote: Counting objects: 100% (1240/1240)\n"
                "Receiving objects: 100% (88/88), 34.2 KiB\n"
            ),
        ),
        _task(
            "launch",
            label="launch fanout visual-auth",
            status="running",
            age_seconds=12,
            live_output=(
                "Launching 3 agents for visual-auth\n"
                "planner: queued\n"
                "coder: running\n"
                "reviewer: waiting for workspace\n"
            ),
        ),
        _running_monitor_row(),
        _finished_monitor_row(),
        _task(
            "mail",
            label="mail sase-41",
            status="success",
            age_seconds=142,
            output="Mailed sase-41 to reviewers.\n",
        ),
        _task(
            "rebase",
            label="rebase sase-40",
            status="error",
            age_seconds=315,
            output="CONFLICT (content): src/sase/ace/tui/app.py\n",
            error="merge conflict",
        ),
        _task(
            "accept",
            label="accept sase-39",
            status="success",
            age_seconds=580,
            output="Accepted mentor proposal and refreshed Patch.\n",
        ),
        *extra_rows,
    )
    app._proc_projection = ProcProjection(
        rows=rows,
        active_count=sum(1 for row in rows if row.status in {"pending", "running"}),
        active_monitor_count=sum(
            1
            for row in rows
            if row.status in {"pending", "running"}
            and row.origin == MONITOR_PROC_ORIGIN
        ),
        session_id="session-mine",
    )
    _attach_monitor_visual_agents(app)

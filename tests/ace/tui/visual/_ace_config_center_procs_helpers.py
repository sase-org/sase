"""Tasks tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

from sase.ace.tui.proc_observer import ObservedProc, ProcProjection

_FIXED_TASK_NOW = datetime(2026, 6, 26, 12, 0, 0)


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
) -> ObservedProc:
    started_at = _FIXED_TASK_NOW.replace(tzinfo=None) - timedelta(seconds=age_seconds)
    info = ObservedProc(
        proc_id=proc_id,
        proc_type=label.split()[0],
        cl_name="",
        project_file="",
        status=status,
        message=f"{label} complete",
        started_at=started_at,
        display_name=label,
        finished_at=started_at if status != "running" else None,
        output=output,
        error=error,
    )
    if live_output is not None:
        info._live_buffer = io.StringIO(live_output)
        info.output = live_output
    return info


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
        session_id="session-mine",
    )

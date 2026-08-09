"""Tasks tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any

from sase.ace.tui.task_queue import TaskInfo

_FIXED_TASK_NOW = datetime(2026, 6, 26, 12, 0, 0)


def _task(
    task_id: str,
    *,
    label: str,
    status: str,
    age_seconds: int,
    output: str = "",
    error: str | None = None,
    live_output: str | None = None,
) -> TaskInfo:
    started_at = _FIXED_TASK_NOW.replace(tzinfo=None) - timedelta(seconds=age_seconds)
    info = TaskInfo(
        task_id=task_id,
        task_type=label.split()[0],
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
    return info


def _seed_tasks_tab_queue(app: Any) -> None:
    queue = app._task_queue
    queue._tasks = {
        task.task_id: task
        for task in (
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
        )
    }

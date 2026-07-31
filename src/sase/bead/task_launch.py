"""Shared host-side launch helpers for standalone task beads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.epic_launch import (
    EpicLaunchOrigin,
    epic_launch_origin_from_gate_source,
    resolve_epic_launch_cwd,
)

if TYPE_CHECKING:
    from sase.tasks.models import BackgroundTask


_TASK_LAUNCH_TAGS = ("task", "launch")
_TASK_LAUNCH_SUBMIT_LOCK = "task-launch-submit"

type TaskLaunchOrigin = EpicLaunchOrigin


def task_launch_origin_from_gate_source(
    source: str | None,
) -> TaskLaunchOrigin:
    """Map a neutral gate response source to its detached-task origin."""
    return epic_launch_origin_from_gate_source(source)


def _build_task_launch_argv(
    task_id: str,
    *,
    feedback: str | None = None,
    yes_to_all: bool = True,
) -> list[str]:
    """Build the canonical standalone task-bead launch command."""
    confirmation_flag = "--yes-to-all" if yes_to_all else "--yes"
    argv = ["sase", "bead", "work", task_id, confirmation_flag]
    feedback_text = feedback.strip() if feedback else ""
    if feedback_text:
        argv.extend(["--launch-feedback", feedback_text])
    return argv


def resolve_task_launch_cwd(
    project_dir: str | Path | None,
    *,
    agent_project_file: str | Path | None = None,
) -> Path:
    """Resolve a task bead's canonical project to its primary checkout."""
    return resolve_epic_launch_cwd(
        project_dir,
        agent_project_file=agent_project_file,
    )


def submit_task_launch_task(
    task_id: str,
    *,
    cwd: str | Path,
    feedback: str | None = None,
    origin: TaskLaunchOrigin = "api",
) -> BackgroundTask:
    """Submit or reuse one globally visible detached task-bead launch."""
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.logs._bounded import log_file_lock
    from sase.tasks import tasks_dir
    from sase.tasks.runner import submit_detached_task

    resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
    project = infer_project_name_from_cwd(str(resolved_cwd))
    with log_file_lock(tasks_dir() / _TASK_LAUNCH_SUBMIT_LOCK):
        if existing := _active_task_launch(task_id):
            return existing
        return submit_detached_task(
            _build_task_launch_argv(task_id, feedback=feedback),
            label=f"Task launch · {task_id}",
            cwd=resolved_cwd,
            origin=origin,
            project=project,
            tags=_TASK_LAUNCH_TAGS,
        )


def _active_task_launch(task_id: str) -> BackgroundTask | None:
    """Return the newest active detached launch for *task_id*, if any."""
    from sase.tasks import (
        ACTIVE_TASK_STATUSES,
        DETACHED_TASK_KIND,
        read_tasks,
    )

    for task in read_tasks(
        status=ACTIVE_TASK_STATUSES,
        kind=DETACHED_TASK_KIND,
    ):
        if not set(_TASK_LAUNCH_TAGS).issubset(task.tags):
            continue
        if len(task.command) < 4 or task.command[:3] != ["sase", "bead", "work"]:
            continue
        if task.command[3] == task_id:
            return task
    return None


__all__ = [
    "TaskLaunchOrigin",
    "resolve_task_launch_cwd",
    "submit_task_launch_task",
    "task_launch_origin_from_gate_source",
]

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
    from sase.procs.models import Proc


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


def _resolve_task_launch_cwd(
    project_dir: str | Path | None,
    *,
    agent_project_file: str | Path | None = None,
) -> Path:
    """Resolve a task bead's canonical project to its primary checkout."""
    return resolve_epic_launch_cwd(
        project_dir,
        agent_project_file=agent_project_file,
    )


def resolve_task_launch_cwd_for_project(project: str) -> Path:
    """Resolve an explicit SASE project key to its primary checkout."""
    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.core.paths import is_valid_sase_project_name, sase_projects_dir

    if not is_valid_sase_project_name(project):
        raise ValueError(f"invalid SASE project key: {project}")
    project_dir = sase_projects_dir() / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        raise FileNotFoundError(f"project file is missing for {project}")
    return _resolve_task_launch_cwd(None, agent_project_file=project_file)


def submit_task_launch_task(
    task_id: str,
    *,
    cwd: str | Path,
    feedback: str | None = None,
    origin: TaskLaunchOrigin = "api",
) -> Proc:
    """Submit or reuse one globally visible detached task-bead launch."""
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.logs._bounded import log_file_lock
    from sase.procs import procs_dir
    from sase.procs.runner import submit_detached_proc

    resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
    project = infer_project_name_from_cwd(str(resolved_cwd))
    with log_file_lock(procs_dir() / _TASK_LAUNCH_SUBMIT_LOCK):
        if existing := _active_task_launch(task_id):
            return existing
        return submit_detached_proc(
            _build_task_launch_argv(task_id, feedback=feedback),
            label=f"Task launch · {task_id}",
            cwd=resolved_cwd,
            origin=origin,
            project=project,
            tags=_TASK_LAUNCH_TAGS,
        )


def submit_task_launch_for_project(
    project: str,
    bead_id: str,
    *,
    feedback: str | None = None,
    origin: TaskLaunchOrigin | None = None,
) -> Proc:
    """Resolve *project* and submit or reuse its detached task launch."""
    return submit_task_launch_task(
        bead_id,
        cwd=resolve_task_launch_cwd_for_project(project),
        feedback=feedback,
        origin=origin or "api",
    )


def _is_task_launch_row(task: Proc) -> bool:
    """Return whether *task* is a detached task-bead launch row."""
    return set(_TASK_LAUNCH_TAGS).issubset(task.tags) and (
        len(task.command) >= 4 and task.command[:3] == ["sase", "bead", "work"]
    )


def active_task_launch_bead_ids() -> frozenset[str]:
    """Return bead IDs with an active detached task-bead launch."""
    from sase.procs import (
        ACTIVE_PROC_STATUSES,
        DETACHED_PROC_KIND,
        read_procs,
    )

    return frozenset(
        task.command[3]
        for task in read_procs(
            status=ACTIVE_PROC_STATUSES,
            kind=DETACHED_PROC_KIND,
        )
        if _is_task_launch_row(task)
    )


def _active_task_launch(task_id: str) -> Proc | None:
    """Return the newest active detached launch for *task_id*, if any."""
    from sase.procs import (
        ACTIVE_PROC_STATUSES,
        DETACHED_PROC_KIND,
        read_procs,
    )

    for task in read_procs(
        status=ACTIVE_PROC_STATUSES,
        kind=DETACHED_PROC_KIND,
    ):
        if _is_task_launch_row(task) and task.command[3] == task_id:
            return task
    return None


__all__ = [
    "TaskLaunchOrigin",
    "active_task_launch_bead_ids",
    "resolve_task_launch_cwd_for_project",
    "submit_task_launch_for_project",
    "submit_task_launch_task",
    "task_launch_origin_from_gate_source",
]

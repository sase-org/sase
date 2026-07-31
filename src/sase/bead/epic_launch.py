"""Shared host-side launch helpers for approved epic plans."""

from __future__ import annotations

import json
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata


if TYPE_CHECKING:
    from sase.tasks.models import BackgroundTask


_EPIC_LAUNCH_TAGS = ("epic", "launch")
_EPIC_LAUNCH_SUBMIT_LOCK = "epic-launch-submit"

type EpicLaunchOrigin = Literal["ace", "telegram", "cli", "axe", "api"]

_GATE_SOURCE_TO_EPIC_LAUNCH_ORIGIN: dict[str, EpicLaunchOrigin] = {
    "tui": "ace",
    "telegram": "telegram",
    "auto_resolution": "axe",
}


def epic_launch_origin_from_gate_source(
    source: str | None,
) -> EpicLaunchOrigin:
    """Map a neutral gate response source to its detached-task origin."""
    return _GATE_SOURCE_TO_EPIC_LAUNCH_ORIGIN.get(source or "", "api")


def build_epic_launch_argv(
    plan_file: str | Path,
    *,
    artifacts_dir: str | Path | None = None,
    cl_name: str | None = None,
    yes_to_all: bool = True,
    expect_prompt_snapshot: bool = True,
) -> list[str]:
    """Build the canonical approved-epic launch command."""
    confirmation_flag = "--yes-to-all" if yes_to_all else "--yes"
    argv = ["sase", "bead", "work", str(plan_file), confirmation_flag]
    if artifacts_dir is not None:
        argv.extend(["--artifacts-dir", str(artifacts_dir)])
    if cl_name:
        argv.extend(["--cl-name", cl_name])
    if expect_prompt_snapshot:
        argv.append("--expect-prompt-snapshot")
    return argv


def resolve_epic_launch_cwd(
    project_dir: str | Path | None,
    *,
    agent_project_file: str | Path | None = None,
) -> Path:
    """Resolve an approved epic's canonical project to its primary checkout."""
    project_file_value = (
        str(agent_project_file).strip() if agent_project_file is not None else ""
    )
    if project_file_value:
        project_name = Path(project_file_value).expanduser().parent.name
        from sase.core.paths import is_valid_sase_project_name

        if not is_valid_sase_project_name(project_name):
            raise ValueError(
                "agent project file does not identify a valid SASE project: "
                f"{agent_project_file}"
            )
    else:
        if project_dir is None or not str(project_dir).strip():
            raise ValueError(
                "project_dir or agent_project_file is required to resolve epic "
                "launch cwd"
            )
        project_path = Path(project_dir).expanduser().resolve(strict=False)
        try:
            from sase.workspace_provider import get_workspace_name

            discovered_name = get_workspace_name(str(project_path))
        except Exception:
            discovered_name = None
        if not discovered_name:
            discovered_name = re.sub(r"_\d+$", "", project_path.name)

        from sase.project_aliases import resolve_project_alias_ref

        project_name = resolve_project_alias_ref(discovered_name)

    from sase.running_field import get_workspace_directory

    primary = Path(get_workspace_directory(project_name, 1)).expanduser()
    if not primary.is_dir():
        raise FileNotFoundError(f"primary workspace is missing: {primary}")
    return primary


def submit_epic_launch_task(
    plan_file: str | Path,
    *,
    cwd: str | Path,
    artifacts_dir: str | Path | None = None,
    cl_name: str | None = None,
    origin: EpicLaunchOrigin = "api",
) -> BackgroundTask:
    """Submit one globally visible task for an approved epic plan.

    Raises:
        TaskSubmitError: The task could not be recorded or its supervisor
            could not be started.
    """
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.logs._bounded import log_file_lock
    from sase.tasks import tasks_dir
    from sase.tasks.runner import submit_detached_task

    resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
    resolved_plan = _resolved_plan_path(plan_file, cwd=resolved_cwd)
    argv = build_epic_launch_argv(
        plan_file,
        artifacts_dir=artifacts_dir,
        cl_name=cl_name,
    )
    project = infer_project_name_from_cwd(str(resolved_cwd))
    with log_file_lock(tasks_dir() / _EPIC_LAUNCH_SUBMIT_LOCK):
        if existing := _active_epic_launch_for_plan(resolved_plan):
            return existing
        return submit_detached_task(
            argv,
            label=f"Epic launch · {Path(plan_file).stem}",
            cwd=resolved_cwd,
            origin=origin,
            project=project,
            tags=_EPIC_LAUNCH_TAGS,
            cl_name=cl_name,
        )


def _active_epic_launch_for_plan(plan_file: Path) -> BackgroundTask | None:
    """Return the newest active detached launch for *plan_file*, if any."""
    from sase.tasks import (
        ACTIVE_TASK_STATUSES,
        DETACHED_TASK_KIND,
        read_tasks,
    )

    for task in read_tasks(
        status=ACTIVE_TASK_STATUSES,
        kind=DETACHED_TASK_KIND,
    ):
        if not set(_EPIC_LAUNCH_TAGS).issubset(task.tags):
            continue
        if len(task.command) < 4 or task.command[:3] != ["sase", "bead", "work"]:
            continue
        if _resolved_plan_path(task.command[3], cwd=task.cwd) == plan_file:
            return task
    return None


def _resolved_plan_path(plan_file: str | Path, *, cwd: str | Path) -> Path:
    path = Path(plan_file).expanduser()
    if not path.is_absolute():
        path = Path(cwd).expanduser() / path
    return path.resolve(strict=False)


def _update_epic_launch_metadata(
    artifacts_dir: str | Path | None,
    *,
    epic_id: str,
    sdd_plan_path: str,
) -> None:
    """Best-effort back-fill of planner metadata after a host launch."""
    if artifacts_dir is None:
        return
    artifacts_path = Path(artifacts_dir).expanduser()
    meta_path = artifacts_path / "agent_meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    data.update(
        {
            "epic_bead_id": epic_id,
            "epic_started_at": datetime.now(UTC).isoformat(),
            "plan_committed": True,
            "sdd_plan_path": sdd_plan_path,
        }
    )
    canonicalize_agent_tribe_metadata(data)
    try:
        meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        from sase.core.agent_artifact_index_lifecycle import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(artifacts_path)
    except Exception:
        return


def finish_epic_launch(
    plan_file: str,
    *,
    artifacts_dir: str | Path | None,
    cl_name: str | None,
    result: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Best-effort approval metadata and notification handling."""
    if artifacts_dir is None and not cl_name:
        return
    if result is not None and bool(getattr(result, "dry_run", False)):
        return

    epic_id = getattr(result, "epic_id", None) if result is not None else None
    archived_plan_path = (
        getattr(result, "archived_plan_path", None) if result is not None else None
    )
    launched = bool(getattr(result, "launched", False)) if result is not None else False
    success = error is None and bool(epic_id) and launched
    if success:
        try:
            _update_epic_launch_metadata(
                artifacts_dir,
                epic_id=str(epic_id),
                sdd_plan_path=str(archived_plan_path or plan_file),
            )
        except Exception:
            pass

    try:
        from sase.bead.epic_launch_handoff import (
            claim_epic_completion,
            fold_epic_launch_outcome,
            send_completion_payload,
        )
        from sase.notifications.senders import notify_workflow_complete

        argv = build_epic_launch_argv(
            plan_file,
            artifacts_dir=artifacts_dir,
            cl_name=cl_name,
            yes_to_all=False,
        )
        if success:
            detail = ""
            notes = [
                f"Epic {epic_id} launched from {Path(plan_file).name}",
                f"Plan: {archived_plan_path or plan_file}",
            ]
        else:
            if error is not None:
                detail = str(error)
            elif epic_id and not launched:
                detail = "epic launch was declined"
            else:
                detail = "epic id was not returned"
            notes = [
                f"Epic launch failed: {detail}",
                f"Resume with: {shlex.join(argv)}",
            ]
        deferred = claim_epic_completion(
            artifacts_dir,
            outcome={
                "success": success,
                "epic_id": str(epic_id) if epic_id is not None else None,
                "plan_file": plan_file,
                "detail": detail,
                "settled_at": datetime.now(UTC).isoformat(),
            },
        )
        if deferred is not None:
            send_completion_payload(
                fold_epic_launch_outcome(
                    deferred,
                    success=success,
                    epic_id=str(epic_id) if epic_id is not None else None,
                    plan_file=plan_file,
                    archived_plan_path=archived_plan_path,
                    detail=detail,
                    resume_argv=argv,
                )
            )
            return
        notify_workflow_complete(
            "epic-launch",
            cl_name,
            success,
            notes,
            tags=["epic", "launch"],
        )
    except Exception:
        pass


__all__ = [
    "EpicLaunchOrigin",
    "build_epic_launch_argv",
    "epic_launch_origin_from_gate_source",
    "finish_epic_launch",
    "resolve_epic_launch_cwd",
    "submit_epic_launch_task",
]

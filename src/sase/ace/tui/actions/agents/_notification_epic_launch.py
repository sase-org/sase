"""Tracked host-owned epic launches for plan-approval notifications."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.epic_launch import (
    build_epic_launch_argv,
    parse_epic_launch_output,
    resolve_epic_launch_cwd,
    update_epic_launch_metadata,
)

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...actions.task_actions import TrackedTaskCompletion, TrackedTaskResult
    from ...task_subprocess import TaskReporter


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EpicLaunchTaskPayload:
    epic_id: str
    sdd_plan_path: str


def submit_epic_launch_task(
    app: object,
    notification: Notification,
    *,
    plan_file: str,
    phase_count: int,
) -> bool:
    """Submit a deduplicated tracked launch before the response claims ownership."""
    project_dir = notification.action_data.get("project_dir")
    if not project_dir:
        return False
    agent_project_file = notification.action_data.get("agent_project_file")

    dedup_key = _epic_launch_dedup_key(plan_file)
    task_queue = getattr(app, "_task_queue", None)
    get_running = getattr(task_queue, "get_running_for_key", None)
    if callable(get_running) and get_running(dedup_key) is not None:
        return True

    submit = getattr(app, "_submit_tracked_task", None)
    if not callable(submit):
        return False

    from ...actions.task_actions import TrackedTaskResult

    def work(reporter: TaskReporter) -> TrackedTaskResult[_EpicLaunchTaskPayload]:
        try:
            cwd = resolve_epic_launch_cwd(
                project_dir,
                agent_project_file=agent_project_file,
            )
        except Exception as exc:
            message = f"Could not resolve the primary workspace: {exc}"
            return TrackedTaskResult(success=False, message=message, error=message)
        reporter.phase("Launching epic")
        completed = reporter.run(build_epic_launch_argv(plan_file), cwd=cwd)
        output = completed.stdout or ""
        parsed = parse_epic_launch_output(output)
        if completed.returncode != 0:
            message = f"Epic launch failed with exit code {completed.returncode}"
            return TrackedTaskResult(success=False, message=message, error=message)
        if parsed.epic_id is None:
            message = "Epic launch output did not contain the required Epic: <id> line"
            return TrackedTaskResult(success=False, message=message, error=message)
        from sase.plan_approval_actions import resolve_plan_agent_artifacts_dir

        artifacts_dir = resolve_plan_agent_artifacts_dir(notification.action_data)
        update_epic_launch_metadata(
            artifacts_dir,
            epic_id=parsed.epic_id,
            sdd_plan_path=parsed.archived_plan_path or plan_file,
        )
        return TrackedTaskResult(
            success=True,
            message=f"Epic {parsed.epic_id} launched",
            payload=_EpicLaunchTaskPayload(
                epic_id=parsed.epic_id,
                sdd_plan_path=parsed.archived_plan_path or plan_file,
            ),
        )

    def on_complete(
        completion: TrackedTaskCompletion[_EpicLaunchTaskPayload],
    ) -> None:
        if completion.success and completion.payload is not None:
            _finish_successful_epic_launch(
                app,
                completion.payload,
                phase_count=phase_count,
            )
            return
        resume = shlex.join(build_epic_launch_argv(plan_file))
        app.notify(  # type: ignore[attr-defined]
            f"See the Tasks tab for output. Resume with: {resume}",
            title="Epic launch failed",
            severity="error",
            timeout=15,
        )

    cl_name = notification.action_data.get("agent_cl_name") or Path(plan_file).stem
    project_file = agent_project_file or str(project_dir)
    try:
        task_info = submit(
            "epic-launch",
            cl_name,
            project_file,
            work,
            display_name=f"Epic launch: {Path(plan_file).stem}",
            dedup_key=dedup_key,
            duplicate_message="This epic plan is already launching",
            on_complete=on_complete,
            reload_on_complete=True,
            notify_on_complete=False,
        )
    except Exception:
        log.warning("Could not submit tracked epic launch", exc_info=True)
        return False
    if task_info is not None:
        return True
    return bool(callable(get_running) and get_running(dedup_key) is not None)


def _finish_successful_epic_launch(
    app: object,
    payload: _EpicLaunchTaskPayload,
    *,
    phase_count: int,
) -> None:
    noun = "agent" if phase_count == 1 else "agents"
    app.notify(  # type: ignore[attr-defined]
        f"{phase_count} phase {noun} + land agent",
        title=f"Epic {payload.epic_id} launched",
    )


def _epic_launch_dedup_key(plan_file: str) -> str:
    path = Path(plan_file).expanduser().absolute()
    return f"epic-launch:{path}"


__all__ = ["submit_epic_launch_task"]

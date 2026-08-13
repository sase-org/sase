"""Shared monitor claim, follow-up, refresh, and notification settlement."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.notifications.senders import (
    notify_monitor_followup_dropped,
    notify_workflow_complete,
)
from sase.running_field import release_workspace

from .followup import FollowupLaunchResult, launch_followup_agent
from .models import MonitorState
from .output import OutputCapture

LOST_FOLLOWUP_ERROR = (
    "follow-up not launched because the monitor was marked lost after a reboot"
)

FollowupLauncher = Callable[..., bool | FollowupLaunchResult]


def settle_claim_and_followup(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    timeout_kind: str | None,
    project_name: str | None,
    transfer_from_pid: int | None = None,
    launch_followup: FollowupLauncher | None = None,
) -> str | None:
    """Launch/record follow-up disposition and dispose of the monitor claim."""
    next_action = meta.get("monitor_next_action")
    if next_action and monitor_state == "lost":
        _record_followup_outcome(artifacts_dir, meta, "not-launchable")
        _record_followup_error(artifacts_dir, meta, LOST_FOLLOWUP_ERROR)
        release_error = _release_monitor_claim(meta, project_name=project_name)
        return release_error or LOST_FOLLOWUP_ERROR

    if next_action and monitor_state != "stopped":
        launch_result = FollowupLaunchResult(launched=False)
        if project_name:
            launcher = launch_followup or launch_followup_agent
            launch_result = _coerce_followup_result(
                launcher(
                    artifacts_dir,
                    meta,
                    monitor_state=monitor_state,
                    exit_code=exit_code,
                    elapsed_seconds=elapsed_seconds,
                    capture=capture,
                    timeout_kind=timeout_kind,
                    project_name=project_name,
                    transfer_from_pid=transfer_from_pid,
                ),
                meta,
            )
        else:
            launch_result = FollowupLaunchResult(
                launched=False,
                error="could not resolve the monitor's project from its artifacts path",
            )
        if launch_result.launched:
            if launch_result.degraded_reason:
                _record_followup_outcome(
                    artifacts_dir,
                    meta,
                    "launched-degraded",
                    degraded_reason=launch_result.degraded_reason,
                )
                release_error = _release_monitor_claim(meta, project_name=project_name)
                return release_error
            _record_followup_outcome(artifacts_dir, meta, "launched")
            return None
        _record_followup_outcome(
            artifacts_dir,
            meta,
            "not-launchable",
            prompt_path=launch_result.prompt_path,
        )
        release_error = _release_monitor_claim(meta, project_name=project_name)
        followup_error = (
            launch_result.error
            or str(meta.get("monitor_followup_error") or "")
            or "follow-up launch failed"
        )
        return release_error or followup_error

    return _release_monitor_claim(meta, project_name=project_name)


def _coerce_followup_result(
    raw: bool | FollowupLaunchResult,
    meta: dict[str, Any],
) -> FollowupLaunchResult:
    if isinstance(raw, FollowupLaunchResult):
        return raw
    if raw:
        return FollowupLaunchResult(
            launched=True,
            agent_name=(
                str(meta["monitor_followup_agent"])
                if meta.get("monitor_followup_agent")
                else None
            ),
        )
    return FollowupLaunchResult(
        launched=False,
        error=str(meta.get("monitor_followup_error") or "") or None,
        prompt_path=(
            str(meta["monitor_followup_prompt_path"])
            if meta.get("monitor_followup_prompt_path")
            else None
        ),
    )


def _release_monitor_claim(
    meta: dict[str, Any],
    *,
    project_name: str | None,
) -> str | None:
    """Release this monitor member's workspace claim, if it can be resolved."""
    workspace_num = meta.get("workspace_num")
    cl_name = meta.get("cl_name")
    if project_name and workspace_num is not None:
        from sase.monitor.start import MONITOR_WORKSPACE_CLAIM_WORKFLOW
        from sase.workflows.utils import get_project_file_path

        result = release_workspace(
            get_project_file_path(project_name),
            int(workspace_num),
            MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            cl_name=cl_name,
        )
        if not result.success:
            return result.error or "workspace release failed"
    return None


def notify_monitor_complete(
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    stop_status: str,
    followup_error: str | None = None,
) -> None:
    """Send the monitor completion notification."""
    cl_name = meta.get("cl_name")
    success = monitor_state in {"completed", "stopped"} and followup_error is None
    notes = [f"{stop_status}: {meta.get('monitor_command')}"]
    notify_workflow_complete(
        "monitor",
        cl_name,
        success,
        notes,
        tags=["monitor"],
    )
    if followup_error:
        # A dropped `--next` strands a lane and must not be lost inside a
        # routine completion note: raise it as its own alarm.
        monitor_id = meta.get("monitor_id") or ""
        notify_monitor_followup_dropped(cl_name, monitor_id, followup_error)


def touch_monitor_refresh_pulse(project_name: str | None) -> None:
    """Nudge artifact watchers after monitor metadata changes."""
    if project_name is None:
        return
    pulse_path = sase_projects_dir() / project_name / "artifacts" / ".ace_refresh_pulse"
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the project containing a monitor artifacts directory."""
    try:
        relative = (
            Path(artifacts_dir)
            .expanduser()
            .resolve()
            .relative_to(sase_projects_dir().resolve())
        )
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


def _record_followup_error(
    artifacts_dir: str,
    meta: dict[str, Any],
    message: str,
) -> None:
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    meta["monitor_followup_error"] = message
    update_meta_field(artifacts_dir, "monitor_followup_error", message)


def _record_followup_outcome(
    artifacts_dir: str,
    meta: dict[str, Any],
    outcome: str,
    *,
    degraded_reason: str | None = None,
    prompt_path: str | None = None,
) -> None:
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    meta["monitor_followup_outcome"] = outcome
    update_meta_field(artifacts_dir, "monitor_followup_outcome", outcome)
    if degraded_reason:
        meta["monitor_followup_degraded_reason"] = degraded_reason
        update_meta_field(
            artifacts_dir,
            "monitor_followup_degraded_reason",
            degraded_reason,
        )
    if prompt_path:
        meta["monitor_followup_prompt_path"] = prompt_path
        update_meta_field(artifacts_dir, "monitor_followup_prompt_path", prompt_path)


__all__ = [
    "LOST_FOLLOWUP_ERROR",
    "notify_monitor_complete",
    "project_name_from_artifacts_dir",
    "settle_claim_and_followup",
    "touch_monitor_refresh_pulse",
]

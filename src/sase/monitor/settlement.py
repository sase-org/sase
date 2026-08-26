"""Monitor claim, follow-up, and refresh settlement facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.running_field import release_workspace
from sase.shells.settlement import (
    ShellSettlementConfig,
    finalize_shell_workflow_state,
    project_name_from_artifacts_dir as shell_project_name_from_artifacts_dir,
    settle_shell_claim_and_followup,
    touch_shell_refresh_pulse,
)

from .followup import FollowupLaunchResult, launch_followup_agent
from .models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME, MonitorState
from .output import OutputCapture

LOST_FOLLOWUP_ERROR = (
    "follow-up not launched because the monitor was marked lost after a reboot"
)

FollowupLauncher = Callable[..., bool | FollowupLaunchResult]

_MONITOR_SETTLEMENT_CONFIG = ShellSettlementConfig(
    next_action_field="monitor_next_action",
    agent_field="monitor_followup_agent",
    outcome_field="monitor_followup_outcome",
    error_field="monitor_followup_error",
    degraded_reason_field="monitor_followup_degraded_reason",
    prompt_path_field="monitor_followup_prompt_path",
    lost_state="lost",
    stopped_state="stopped",
    lost_followup_error=LOST_FOLLOWUP_ERROR,
    degraded_outcome=MONITOR_FOLLOWUP_DEGRADED_OUTCOME,
    fallback_followup_error="follow-up launch failed",
    missing_project_error=(
        "could not resolve the monitor's project from its artifacts path"
    ),
)


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
    launcher = launch_followup or launch_followup_agent
    return settle_shell_claim_and_followup(
        artifacts_dir,
        meta,
        shell_state=monitor_state,
        project_name=project_name,
        config=_MONITOR_SETTLEMENT_CONFIG,
        release_claim=_release_monitor_claim_positional,
        launch_followup=launcher,
        launch_kwargs={
            "monitor_state": monitor_state,
            "exit_code": exit_code,
            "elapsed_seconds": elapsed_seconds,
            "capture": capture,
            "timeout_kind": timeout_kind,
            "project_name": project_name,
            "transfer_from_pid": transfer_from_pid,
        },
        update_meta_field=update_meta_field,
    )


def _release_monitor_claim_positional(
    meta: dict[str, Any],
    project_name: str | None,
) -> str | None:
    return _release_monitor_claim(meta, project_name=project_name)


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


def touch_monitor_refresh_pulse(project_name: str | None) -> None:
    """Nudge artifact watchers after monitor metadata changes."""
    touch_shell_refresh_pulse(project_name)


def finalize_monitor_workflow_state(artifacts_dir: str) -> None:
    """Rewrite a settled monitor member's workflow_state.json to terminal."""
    finalize_shell_workflow_state(artifacts_dir)


def project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the project containing a monitor artifacts directory."""
    return shell_project_name_from_artifacts_dir(artifacts_dir)


__all__ = [
    "LOST_FOLLOWUP_ERROR",
    "finalize_monitor_workflow_state",
    "project_name_from_artifacts_dir",
    "settle_claim_and_followup",
    "touch_monitor_refresh_pulse",
]

"""Monitor claim, follow-up, and refresh settlement facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
from .host_completion import HOST_COMPLETED_OUTCOME, settle_host_completion
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


@dataclass(frozen=True, slots=True)
class _MonitorFollowupSettlementResult:
    """Disposition recorded while settling a monitor follow-up."""

    error: str | None = None
    launch_result: FollowupLaunchResult | None = None


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
) -> _MonitorFollowupSettlementResult:
    """Launch/record follow-up disposition and dispose of the monitor claim."""
    launcher = launch_followup or launch_followup_agent
    captured_launch_result: FollowupLaunchResult | None = None

    def launch_and_capture(*args: Any, **kwargs: Any) -> FollowupLaunchResult:
        nonlocal captured_launch_result
        raw = launcher(*args, **kwargs)
        captured_launch_result = _coerce_monitor_followup_result(raw, meta)
        return captured_launch_result

    blocked_reason = None
    if monitor_state not in ("stopped", "lost"):
        blocked_reason = _continuation_dispatch_blocked_reason(meta)
    if blocked_reason:
        meta[_MONITOR_SETTLEMENT_CONFIG.outcome_field] = "not-launchable"
        meta[_MONITOR_SETTLEMENT_CONFIG.error_field] = blocked_reason
        update_meta_field(
            artifacts_dir,
            _MONITOR_SETTLEMENT_CONFIG.outcome_field,
            "not-launchable",
        )
        update_meta_field(
            artifacts_dir,
            _MONITOR_SETTLEMENT_CONFIG.error_field,
            blocked_reason,
        )
        release_error = _release_monitor_claim_positional(meta, project_name)
        return _MonitorFollowupSettlementResult(
            error=release_error or blocked_reason,
            launch_result=FollowupLaunchResult(
                launched=False,
                error=blocked_reason,
            ),
        )

    from sase.monitor.outcome_policy import (
        apply_frozen_branch,
        frozen_action,
        settlement_policy_decision,
        should_launch_frozen_followup,
    )

    decision = settlement_policy_decision(artifacts_dir, meta, monitor_state)
    if frozen_action(decision) == "complete":
        completion_ref = decision.get("completion_ref")
        if isinstance(completion_ref, str) and completion_ref.strip():
            meta.setdefault("monitor_completion_ref", completion_ref.strip())
        host_settlement = settle_host_completion(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,
            exit_code=exit_code,
            elapsed_seconds=elapsed_seconds,
            project_name=project_name,
            launch_recovery=launch_and_capture,
            release_claim=_release_monitor_claim_positional,
            selected_action="complete",
        )
        if host_settlement is not None:
            captured_launch_result = (
                host_settlement.launch_result or captured_launch_result
            )
            if (
                captured_launch_result is not None
                and captured_launch_result.host_completed
                and not meta.get(_MONITOR_SETTLEMENT_CONFIG.outcome_field)
            ):
                meta[_MONITOR_SETTLEMENT_CONFIG.outcome_field] = HOST_COMPLETED_OUTCOME
                update_meta_field(
                    artifacts_dir,
                    _MONITOR_SETTLEMENT_CONFIG.outcome_field,
                    HOST_COMPLETED_OUTCOME,
                )
            return _MonitorFollowupSettlementResult(
                error=host_settlement.error, launch_result=captured_launch_result
            )

    if should_launch_frozen_followup(decision, monitor_state):
        apply_frozen_branch(artifacts_dir, meta, decision)
    elif monitor_state not in ("stopped", "lost"):
        meta.pop(_MONITOR_SETTLEMENT_CONFIG.next_action_field, None)

    error = settle_shell_claim_and_followup(
        artifacts_dir,
        meta,
        shell_state=monitor_state,
        project_name=project_name,
        config=_MONITOR_SETTLEMENT_CONFIG,
        release_claim=_release_monitor_claim_positional,
        launch_followup=launch_and_capture,
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
    return _MonitorFollowupSettlementResult(
        error=error, launch_result=captured_launch_result
    )


def _continuation_dispatch_blocked_reason(meta: dict[str, Any]) -> str | None:
    from sase.continuation_capture import continuation_dispatch_blocked_reason

    return continuation_dispatch_blocked_reason(meta)


def _coerce_monitor_followup_result(
    raw: bool | FollowupLaunchResult,
    meta: dict[str, Any],
) -> FollowupLaunchResult:
    """Coerce legacy boolean monitor follow-up launchers into a result."""
    if isinstance(raw, FollowupLaunchResult):
        return raw
    if raw:
        agent = meta.get(_MONITOR_SETTLEMENT_CONFIG.agent_field)
        return FollowupLaunchResult(
            launched=True,
            agent_name=agent if isinstance(agent, str) and agent else None,
        )
    error = meta.get(_MONITOR_SETTLEMENT_CONFIG.error_field)
    prompt_path = meta.get(_MONITOR_SETTLEMENT_CONFIG.prompt_path_field)
    return FollowupLaunchResult(
        launched=False,
        error=error if isinstance(error, str) and error else None,
        prompt_path=prompt_path
        if isinstance(prompt_path, str) and prompt_path
        else None,
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

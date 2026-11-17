"""Build the monitor-start request for a durable rerun."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.hijack.recover_common import RecoveryRefusal, clean_string


def load_rerun_descriptor(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable monitor recovery descriptor for rerun."""
    from sase.agent.hijack._preview_monitor import (
        MONITOR_FOLLOWUP_KIND,
        _load_monitor_recovery_descriptor,
    )

    suppressed = record.get("suppressed_followup")
    if (
        not isinstance(suppressed, Mapping)
        or suppressed.get("kind") != MONITOR_FOLLOWUP_KIND
    ):
        raise RecoveryRefusal(
            "rerun_unavailable",
            "monitor recovery descriptor is unavailable; cannot Re-run command",
        )
    ref = clean_string(suppressed.get("ref"))
    if not ref:
        raise RecoveryRefusal(
            "rerun_unavailable",
            "monitor recovery descriptor is unavailable; cannot Re-run command",
        )
    descriptor, error = _load_monitor_recovery_descriptor(ref)
    if descriptor is None:
        raise RecoveryRefusal(
            "rerun_unavailable",
            error
            or "monitor recovery descriptor is unavailable; cannot Re-run command",
        )
    if not clean_string(descriptor.get("command")):
        raise RecoveryRefusal(
            "rerun_unavailable",
            "monitor command is unavailable; cannot Re-run command",
        )
    return dict(descriptor)


def build_rerun_request(
    record: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    *,
    project_name: str,
    session_base: str,
    custody_pid: Any,
) -> Any:
    """Build a fresh ``StartMonitorRequest`` for the recorded command."""
    from sase.monitor.request import StartMonitorRequest

    command = clean_string(descriptor.get("command"))
    if not command:
        raise RecoveryRefusal(
            "rerun_unavailable",
            "monitor command is unavailable; cannot Re-run command",
        )
    workspace_dir = clean_string(record.get("workspace_dir")) or clean_string(
        descriptor.get("workspace_dir")
    )
    if not workspace_dir:
        raise RecoveryRefusal(
            "rerun_unavailable",
            "held workspace is unavailable; cannot Re-run command",
        )
    cwd = clean_string(descriptor.get("cwd")) or workspace_dir
    timeout_seconds = _positive_float(descriptor.get("timeout_seconds"), default=3600.0)
    idle_timeout = _positive_float(
        descriptor.get("idle_timeout_seconds"), default=0.0, allow_zero=True
    )
    followup = descriptor.get("followup")
    followup = followup if isinstance(followup, Mapping) else {}
    next_action = clean_string(followup.get("monitor_next_action"))
    next_model = clean_string(followup.get("monitor_next_model"))
    next_output = clean_string(descriptor.get("output_policy")) or clean_string(
        followup.get("monitor_next_output")
    )
    execution_argv = descriptor.get("execution_argv")
    argv: list[str] | None = None
    if isinstance(execution_argv, (list, tuple)) and all(
        isinstance(item, str) for item in execution_argv
    ):
        argv = [str(item) for item in execution_argv]
    transfer_pid: int | None = None
    if isinstance(custody_pid, int) and not isinstance(custody_pid, bool):
        transfer_pid = custody_pid
    old_monitor = clean_string(descriptor.get("monitor_id")) or "monitor"
    return StartMonitorRequest(
        command=command,
        reason=f"rerun hijacked monitor {old_monitor}",
        timeout_seconds=float(timeout_seconds),
        cwd=cwd,
        project_name=project_name,
        start_status="Running",
        stop_status="Stopped",
        lane=session_base,
        label=None,
        next_action=next_action,
        next_model=next_model,
        tail_lines=200,
        idle_timeout_seconds=float(idle_timeout),
        next_output=next_output or "tail",
        inherit_lane_workspace_claim=True,
        transfer_claim_from_pid=transfer_pid,
        execution_argv=argv,
        completion_ref=None,
        profile=None,
        policy_digest=None,
        outcome_policy=None,
        cli_evidence=None,
        checkpoint_ref=None,
        checkpoint_document=None,
        parent_node_ids=(),
        starter_run_id=None,
        queue_weight_override=None,
        join_run_id=None,
    )


def _positive_float(value: Any, *, default: float, allow_zero: bool = False) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number < 0.0 or (number == 0.0 and not allow_zero):
        return default
    return number


__all__ = ["build_rerun_request", "load_rerun_descriptor"]

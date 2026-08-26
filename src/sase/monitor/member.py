"""Create the monitor member's artifacts directory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sase.shells.member import create_family_shell_member

_MONITOR_INHERITED_METADATA_FIELDS = ("agent_clan", "agent_clan_generation")


def create_monitor_member(
    project_name: str,
    base_meta: dict[str, Any],
    *,
    lane: str,
    suffix: str,
    prev_artifacts_timestamp: str,
    workspace_num: int | None,
    monitor_id: str,
    command: str,
    cwd: str,
    label: str,
    reason: str,
    next_action: str | None,
    start_status: str,
    stop_status: str,
    timeout_seconds: float,
    tail_lines: int,
    next_output: str,
    request_fingerprint: str,
    idle_timeout_seconds: float = 0.0,
    starter_agent: str | None = None,
    next_model: str | None = None,
    execution_argv: Sequence[str] | None = None,
) -> str:
    """Create a monitor family member's artifacts directory.

    Inherits ``create_followup_artifacts()``-shaped metadata from the
    selected parent artifact (model, provider, workspace, Patch/bead
    lineage, ...) so a later follow-up agent inherits it too, then layers
    on the ``monitor_*`` fields that describe the supervised command
    itself.
    """
    monitor_metadata: dict[str, Any] = {
        "monitor_id": monitor_id,
        "proc_id": monitor_id,
        # The selected agent's pid is not this new proc shell's pid.  Keep
        # it empty until the detached supervisor reports its real pid.
        "pid": None,
        "monitor_command": command,
        "monitor_cwd": cwd,
        "monitor_label": label,
        "monitor_reason": reason,
        "monitor_start_status": start_status,
        "monitor_stop_status": stop_status,
        "monitor_timeout_seconds": timeout_seconds,
        "monitor_tail_lines": tail_lines,
        "monitor_next_output": next_output,
        "monitor_state": "running",
        "monitor_settled": False,
        "monitor_request_fingerprint": request_fingerprint,
    }
    if idle_timeout_seconds > 0:
        monitor_metadata["monitor_idle_timeout_seconds"] = idle_timeout_seconds
    if next_action:
        monitor_metadata["monitor_next_action"] = next_action
    if next_model:
        monitor_metadata["monitor_next_model"] = next_model
    if starter_agent:
        monitor_metadata["monitor_starter_agent"] = starter_agent
    if execution_argv:
        monitor_metadata["monitor_execution_argv"] = [
            str(part) for part in execution_argv
        ]

    return create_family_shell_member(
        project_name,
        base_meta,
        family=lane,
        suffix=suffix,
        prev_artifacts_timestamp=prev_artifacts_timestamp,
        workspace_num=workspace_num,
        shell_kind="proc",
        family_role="monitor",
        metadata=monitor_metadata,
        inherited_metadata_fields=_MONITOR_INHERITED_METADATA_FIELDS,
    )


__all__ = ["create_monitor_member"]

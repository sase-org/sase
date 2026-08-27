"""Create the gate-shell member's artifacts directory."""

from __future__ import annotations

from typing import Any

from sase.notification_gates.model_shell import GateShellSpec
from sase.shells.member import create_family_shell_member

_GATE_INHERITED_METADATA_FIELDS = ("agent_clan", "agent_clan_generation")


def create_gate_shell_member(
    project_name: str,
    base_meta: dict[str, Any],
    *,
    lane: str,
    suffix: str,
    prev_artifacts_timestamp: str,
    workspace_num: int | None,
    gate_id: str,
    gate_kind: str,
    label: str,
    reason: str,
    creator_agent: str | None,
    timeout_seconds: float,
    request_fingerprint: str | None,
    shell: GateShellSpec,
) -> str:
    """Create a pending gate-shell family member."""
    next_output = ",".join(shell.next.output)
    gate_metadata: dict[str, Any] = {
        "gate_id": gate_id,
        "gate_kind": gate_kind,
        "gate_state": "pending",
        "gate_start_status": shell.pending_status,
        "gate_stop_status": shell.settled_status,
        "gate_accent": shell.accent,
        "gate_label": label,
        "gate_reason": reason,
        "gate_creator_agent": creator_agent,
        "gate_timeout_seconds": timeout_seconds,
        "gate_request_fingerprint": request_fingerprint,
        "gate_workspace_policy": shell.workspace,
        "gate_next_fork": shell.next.fork,
        "gate_next_output": next_output,
        "gate_next_raw_prompt": shell.next.raw_prompt,
        "proc_id": None,
        "pid": None,
    }
    if shell.next.prompt:
        gate_metadata["gate_next_action"] = shell.next.prompt
    if shell.next.model:
        gate_metadata["gate_next_model"] = shell.next.model
    if shell.next.suffix:
        gate_metadata["gate_next_suffix"] = shell.next.suffix
    if shell.next.role:
        gate_metadata["gate_next_role"] = shell.next.role

    return create_family_shell_member(
        project_name,
        base_meta,
        family=lane,
        suffix=suffix,
        prev_artifacts_timestamp=prev_artifacts_timestamp,
        workspace_num=workspace_num,
        shell_kind="gate",
        family_role="gate",
        metadata=gate_metadata,
        inherited_metadata_fields=_GATE_INHERITED_METADATA_FIELDS,
    )


__all__ = ["create_gate_shell_member"]

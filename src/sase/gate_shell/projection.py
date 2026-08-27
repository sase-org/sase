"""JSON-safe runtime projection of one gate-shell record.

Shared by every surface that reports a gate shell's live state -- ``sase
gate list``/``show``/``cancel`` and the ACE ``GATE`` section -- so "what is
this gate shell doing right now" is computed once, not reimplemented per
surface.
"""

from __future__ import annotations

from typing import Any

from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.naming import short_gate_shell_id
from sase.gate_shell.status import effective_gate_status, gate_status_pair


def gate_shell_followup_needs_attention(record: GateShellRecord) -> bool:
    """Return whether a recorded follow-up did not launch cleanly."""
    return bool(record.followup_error) or bool(record.followup_degraded_reason)


def _gate_shell_holds_workspace_claim(record: GateShellRecord) -> bool:
    """Return whether a still-pending shell is holding a workspace claim (R2)."""
    return not record.is_terminal and record.workspace_policy == "inherit"


def gate_shell_runtime_json(record: GateShellRecord) -> dict[str, Any]:
    """Return the stable runtime JSON shape shared by list/show/cancel."""
    pair = gate_status_pair(record.start_status, record.stop_status)
    status_label = effective_gate_status(
        pair, gate_state=record.gate_state, settled=record.is_terminal
    )
    return {
        "gate_id": record.gate_id,
        "short_id": short_gate_shell_id(record.gate_id),
        "member_agent_name": record.member_agent_name,
        "lane": record.lane,
        "project_name": record.project_name,
        "artifacts_dir": record.artifacts_dir,
        "timestamp": record.timestamp,
        "kind": record.kind,
        "label": record.label,
        "reason": record.reason,
        "start_status": record.start_status,
        "stop_status": record.stop_status,
        "status_label": status_label,
        "accent": record.accent,
        "gate_state": record.gate_state,
        "status_bucket": record.status_bucket,
        "is_terminal": record.is_terminal,
        "creator_agent": record.creator_agent,
        "bundle_path": record.bundle_path,
        "notification_id": record.notification_id,
        "timeout_seconds": record.timeout_seconds,
        "workspace_policy": record.workspace_policy,
        "holds_workspace_claim": _gate_shell_holds_workspace_claim(record),
        "next_action": record.next_action,
        "next_fork": record.next_fork,
        "next_output": record.next_output,
        "next_model": record.next_model,
        "followup_agent": record.followup_agent,
        "followup_outcome": record.followup_outcome,
        "followup_error": record.followup_error,
        "followup_degraded_reason": record.followup_degraded_reason,
        "followup_needs_attention": gate_shell_followup_needs_attention(record),
    }


__all__ = [
    "gate_shell_followup_needs_attention",
    "gate_shell_runtime_json",
]

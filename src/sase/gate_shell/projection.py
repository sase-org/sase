"""JSON-safe runtime projection of one gate-shell record.

Shared by every surface that reports a gate shell's live state -- ``sase
gate list``/``show``/``cancel`` and the ACE ``GATE`` section -- so "what is
this gate shell doing right now" is computed once, not reimplemented per
surface.
"""

from __future__ import annotations

from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.gate_shell.handoff import classify_gate_handoff, resume_command_for
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.naming import short_gate_shell_id
from sase.gate_shell.status import effective_gate_status, gate_status_pair

_SUCCESS_OUTCOMES = frozenset({"launched", "launched-degraded", "suppressed"})


def gate_shell_followup_needs_attention(record: GateShellRecord) -> bool:
    """Return whether a recorded follow-up did not launch cleanly."""
    if bool(record.followup_error) or bool(record.followup_degraded_reason):
        return True
    if not record.is_terminal:
        return False
    if record.followup_outcome in _SUCCESS_OUTCOMES:
        return False
    if not record.next_action:
        return False
    try:
        decision = classify_gate_handoff(
            {
                "gate_id": record.gate_id,
                "gate_kind": record.kind,
                "gate_state": record.gate_state,
                "gate_request_fingerprint": record.request_fingerprint,
                "gate_followup_outcome": record.followup_outcome,
                "gate_followup_agent": record.followup_agent,
                "gate_followup_error": record.followup_error,
                "gate_followup_degraded_reason": record.followup_degraded_reason,
                "gate_followup_prompt_path": record.followup_prompt_path,
                "gate_followup_attempt_id": record.followup_attempt_id,
                "gate_followup_attempt_stage": record.followup_attempt_stage,
                "gate_followup_error_stage": record.followup_error_stage,
                "gate_followup_error_type": record.followup_error_type,
            },
            mode="diagnose",
            already_settled=True,
            followup_requested=bool(record.next_action),
        )
    except (OSError, RuntimeError, ValueError, TypeError):
        return True
    return bool(decision.get("needs_attention"))


def _gate_shell_holds_workspace_claim(
    record: GateShellRecord, *, needs_attention: bool | None = None
) -> bool:
    """Return whether this shell is still holding a workspace claim."""
    if record.workspace_policy != "inherit":
        return False
    if not record.is_terminal:
        return True
    pid = record.claim_holder_pid
    if pid is None:
        return False
    incomplete = (
        gate_shell_followup_needs_attention(record)
        if needs_attention is None
        else needs_attention
    )
    if not incomplete:
        return False
    try:
        return is_process_running(pid)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def gate_shell_runtime_json(record: GateShellRecord) -> dict[str, Any]:
    """Return the stable runtime JSON shape shared by list/show/cancel."""
    pair = gate_status_pair(record.start_status, record.stop_status)
    status_label = effective_gate_status(
        pair, gate_state=record.gate_state, settled=record.is_terminal
    )
    needs_attention = gate_shell_followup_needs_attention(record)
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
        "holds_workspace_claim": _gate_shell_holds_workspace_claim(
            record, needs_attention=needs_attention
        ),
        "next_action": record.next_action,
        "next_fork": record.next_fork,
        "next_output": record.next_output,
        "next_model": record.next_model,
        "followup_agent": record.followup_agent,
        "followup_outcome": record.followup_outcome,
        "followup_error": record.followup_error,
        "followup_degraded_reason": record.followup_degraded_reason,
        "followup_needs_attention": needs_attention,
        "followup_resume_command": (
            resume_command_for(
                {
                    "gate_id": record.gate_id,
                    "gate_kind": record.kind,
                }
            )
            if needs_attention
            else None
        ),
    }


__all__ = [
    "gate_shell_followup_needs_attention",
    "gate_shell_runtime_json",
]

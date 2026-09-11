"""Compact presentation helpers for monitor results and continuations."""

from __future__ import annotations

from typing import Any

from .models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME

HOST_COMPLETED_OUTCOME = "host-completed"
HOST_COMPLETION_FINALIZING_STATUS = "finalizing"
HOST_COMPLETION_DONE_STATUS = "completed_by_host"


def monitor_result_summary(
    *,
    monitor_state: str | None,
    exit_code: int | None = None,
    profile: str | None = None,
) -> str:
    """Return a compact human summary of the monitor command outcome."""
    if monitor_state == "running":
        return "Command running"
    if monitor_state == "completed":
        if profile == "verify":
            return "Required checks passed"
        return "Command completed"
    if monitor_state == "failed":
        if exit_code is not None:
            return f"Command failed (exit {exit_code})"
        return "Command failed"
    if monitor_state == "timeout":
        return "Command timed out"
    if monitor_state == "stopped":
        return "Stopped by request"
    if monitor_state == "lost":
        return "Outcome unknown; supervisor lost"
    return "Outcome pending"


def monitor_next_summary(
    *,
    monitor_state: str | None,
    next_action: str | None = None,
    next_model: str | None = None,
    followup_agent: str | None = None,
    followup_outcome: str | None = None,
    followup_error: str | None = None,
    followup_degraded_reason: str | None = None,
    completion_ref: str | None = None,
    host_completion_status: str | None = None,
    host_completion_message: str | None = None,
) -> str:
    """Return a compact human summary of the continuation disposition."""
    if followup_outcome == HOST_COMPLETED_OUTCOME:
        return "Completed by host"
    if host_completion_status == HOST_COMPLETION_DONE_STATUS:
        return host_completion_message or "Completed by host"
    if host_completion_status == HOST_COMPLETION_FINALIZING_STATUS:
        return "Finalizing"
    if followup_error:
        return f"Needs attention - {followup_error}"
    if followup_outcome == MONITOR_FOLLOWUP_DEGRADED_OUTCOME:
        reason = followup_degraded_reason or "degraded workspace"
        if followup_agent:
            return f"Continuing - {followup_agent} - {reason}"
        return f"Continuing - {reason}"
    if followup_agent:
        model = next_model or "inherited model"
        return f"Continuing - {followup_agent} - {model}"
    if completion_ref and monitor_state == "completed":
        return "Finalizing"
    if monitor_state in {"stopped", "lost"}:
        return "No continuation"
    if next_action:
        model = next_model or "inherited model"
        return f"Ready to continue - {model}"
    return "None"


def monitor_evidence_summary(
    *,
    next_output: str | None,
    output_truncated: bool = False,
    diagnostic_manifest_ref: str | None = None,
    retained_log_ref: str | None = None,
    monitor_result_ref: str | None = None,
) -> str:
    """Return a compact human summary of retained evidence."""
    mode = next_output or "auto"
    details: list[str] = []
    if diagnostic_manifest_ref:
        details.append("diagnostics")
    if monitor_result_ref:
        details.append("result ref")
    if retained_log_ref:
        details.append("retained log")
    if output_truncated:
        details.append("truncated")
    if details:
        return f"{mode} - {', '.join(details)}"
    if mode == "file":
        return "file - refs and log locators"
    if mode == "none":
        return "none - inspect on demand"
    if mode == "tail":
        return "tail - retained output tail"
    return "auto - outcome-aware evidence"


def monitor_result_object(
    *,
    monitor_state: str | None,
    exit_code: int | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return the JSON object for the monitor result view model."""
    return {
        "state": monitor_state,
        "exit_code": exit_code,
        "profile": profile,
        "summary": monitor_result_summary(
            monitor_state=monitor_state,
            exit_code=exit_code,
            profile=profile,
        ),
    }


def monitor_continuation_object(
    *,
    monitor_state: str | None,
    next_action: str | None = None,
    next_model: str | None = None,
    next_output: str | None = None,
    followup_agent: str | None = None,
    followup_outcome: str | None = None,
    followup_error: str | None = None,
    followup_degraded_reason: str | None = None,
    followup_prompt_path: str | None = None,
    completion_ref: str | None = None,
    host_completion_status: str | None = None,
    host_completion_message: str | None = None,
    host_completion_reason: str | None = None,
    continuation_node_ref: str | None = None,
    continuation_manifest_ref: str | None = None,
) -> dict[str, Any]:
    """Return the JSON object for the monitor continuation view model."""
    return {
        "next_action": next_action,
        "next_model": next_model,
        "next_output": next_output,
        "followup_agent": followup_agent,
        "followup_outcome": followup_outcome,
        "followup_error": followup_error,
        "followup_degraded_reason": followup_degraded_reason,
        "followup_prompt_path": followup_prompt_path,
        "completion_ref": completion_ref,
        "host_completion_status": host_completion_status,
        "host_completion_message": host_completion_message,
        "host_completion_reason": host_completion_reason,
        "continuation_node_ref": continuation_node_ref,
        "continuation_manifest_ref": continuation_manifest_ref,
        "summary": monitor_next_summary(
            monitor_state=monitor_state,
            next_action=next_action,
            next_model=next_model,
            followup_agent=followup_agent,
            followup_outcome=followup_outcome,
            followup_error=followup_error,
            followup_degraded_reason=followup_degraded_reason,
            completion_ref=completion_ref,
            host_completion_status=host_completion_status,
            host_completion_message=host_completion_message,
        ),
    }


def monitor_evidence_object(
    *,
    next_output: str | None,
    output_truncated: bool = False,
    diagnostic_manifest_ref: str | None = None,
    retained_log_ref: str | None = None,
    monitor_result_id: str | None = None,
    monitor_result_ref: str | None = None,
    requested_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the JSON object for the monitor evidence view model."""
    return {
        "mode": next_output or "auto",
        "diagnostic_manifest_ref": diagnostic_manifest_ref,
        "retained_log_ref": retained_log_ref,
        "monitor_result_id": monitor_result_id,
        "monitor_result_ref": monitor_result_ref,
        "output_truncated": output_truncated,
        "requested_output": requested_output,
        "summary": monitor_evidence_summary(
            next_output=next_output,
            output_truncated=output_truncated,
            diagnostic_manifest_ref=diagnostic_manifest_ref,
            retained_log_ref=retained_log_ref,
            monitor_result_ref=monitor_result_ref,
        ),
    }


def monitor_context_budget_object(
    *,
    budget_decision_path: str | None = None,
) -> dict[str, Any]:
    """Return the JSON object for context-budget evidence."""
    return {
        "budget_decision_path": budget_decision_path,
        "summary": "Budget decision recorded" if budget_decision_path else "Inherited",
    }


__all__ = [
    "HOST_COMPLETED_OUTCOME",
    "HOST_COMPLETION_DONE_STATUS",
    "HOST_COMPLETION_FINALIZING_STATUS",
    "monitor_context_budget_object",
    "monitor_continuation_object",
    "monitor_evidence_object",
    "monitor_evidence_summary",
    "monitor_next_summary",
    "monitor_result_object",
    "monitor_result_summary",
]

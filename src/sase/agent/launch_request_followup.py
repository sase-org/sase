"""Settle-time next-action text for LaunchApproval gate-shell follow-ups."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.launch_request_continuation import (
    RESUME_REQUESTER,
    TERMINAL_HANDOFF,
)


def launch_next_action(
    *,
    envelope: dict[str, Any],
    response: dict[str, Any],
    gate_state: str | None = None,
    declared: str | None = None,
    **_: Any,
) -> str | None:
    """Return the continuation prompt for the settled launch gate."""

    payload = envelope.get("payload")
    request = payload if isinstance(payload, Mapping) else {}
    continuation = request.get("requester_continuation")
    if not isinstance(continuation, Mapping):
        return declared
    mode = str(continuation.get("mode") or "")
    if mode == TERMINAL_HANDOFF:
        return None
    if mode != RESUME_REQUESTER:
        return declared

    branch = _settlement_branch(gate_state, response)
    if branch not in {str(item) for item in continuation.get("resume_branches") or []}:
        return None

    lines = [
        "Continue the original requester after this LaunchApproval gate settles.",
        "",
        *_identity_lines(continuation),
        "",
        _outcome_instruction(branch, response),
        "Review the gate decision, reviewer note, and command results above "
        "before continuing.",
    ]
    return "\n".join(line for line in lines if line is not None).rstrip()


def _settlement_branch(gate_state: str | None, response: Mapping[str, Any]) -> str:
    if gate_state in {"answered", "completed"}:
        selected = response.get("selected_option_ids")
        if isinstance(selected, list):
            return "+".join(str(item) for item in selected)
        return ""
    if gate_state in {"timeout", "stopped", "failed"}:
        return gate_state
    if gate_state == "lost":
        return "failed"
    return "failed"


def _identity_lines(continuation: Mapping[str, Any]) -> list[str]:
    context = continuation.get("context")
    context = context if isinstance(context, Mapping) else {}
    rows = [
        ("Requester", _first(context, "agent_meta.name", "SASE_AGENT_NAME")),
        ("Assignment bead", _first(context, "SASE_BEAD_ID")),
        ("Workflow", _first(context, "SASE_AGENT_WORKFLOW_NAME")),
        (
            "Workspace",
            _first(context, "agent_meta.workspace_dir", "SASE_ACTIVE_PROJECT_DIR"),
        ),
        ("Family", _first(context, "agent_meta.agent_family")),
        ("Family role", _first(context, "agent_meta.agent_family_role")),
        ("Checkpoint", _clean(continuation.get("checkpoint"))),
    ]
    return [f"{label}: {value}" for label, value in rows if value]


def _outcome_instruction(branch: str, response: Mapping[str, Any]) -> str:
    if branch == "approve":
        result = _option_result(response, "approve")
        dispatch_status = _clean(result.get("dispatch_status"))
        if dispatch_status == "failed":
            return (
                "Approve was selected, but dispatch failed. Treat this as a "
                "recoverable launch failure, report the blocker, and do not "
                "assume any helper is running."
            )
        if _approval_dispatch_is_partial(result):
            return (
                "Approve was selected, but dispatch was partial or uncertain. "
                "Inspect admission_summary and unit_results before deciding "
                "whether the requester can continue."
            )
        return (
            "Approve was selected and helpers were launched. Use the typed "
            "launch result details above as the durable handoff record."
        )
    if branch == "reject":
        return (
            "The launch was rejected. Use any reviewer feedback above to "
            "revise or report a blocker; do not silently re-request the same "
            "launch."
        )
    if branch == "timeout":
        return (
            "The launch approval timed out. Continue deliberately by reporting "
            "the timeout or requesting a revised launch only if that is still "
            "the right next step."
        )
    return (
        "The launch gate failed before a clean approval result was available. "
        "Surface the recoverable failure and decide the next action from the "
        "recorded gate state."
    )


def _approval_dispatch_is_partial(result: Mapping[str, Any]) -> bool:
    if result.get("admission_complete") is False:
        return True
    summary = result.get("admission_summary")
    if isinstance(summary, Mapping):
        for key in ("condition_errors", "launch_errors", "skipped"):
            value = summary.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return True
    unit_results = result.get("unit_results")
    if isinstance(unit_results, list):
        for item in unit_results:
            if isinstance(item, Mapping) and item.get("outcome") != "launched":
                return True
    return False


def _option_result(response: Mapping[str, Any], option_id: str) -> Mapping[str, Any]:
    raw_results = response.get("option_results")
    if not isinstance(raw_results, list):
        return {}
    for entry in raw_results:
        if not isinstance(entry, Mapping) or entry.get("id") != option_id:
            continue
        result = entry.get("result")
        return result if isinstance(result, Mapping) else {}
    return {}


def _first(context: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clean(context.get(key))
        if value:
            return value
    return None


def _clean(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["launch_next_action"]

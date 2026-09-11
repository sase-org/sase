"""Requester-continuation contract for agent-origin LaunchApproval gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.launch_request_types import LaunchRequestError

LAUNCH_REQUESTER_CONTINUATION_SCHEMA_VERSION = 1
RESUME_REQUESTER = "resume_requester"
TERMINAL_HANDOFF = "terminal_handoff"
RESUMING_BRANCHES = ("approve", "reject", "timeout", "failed")
TERMINAL_BRANCHES = ("stopped",)

_VALID_MODES = frozenset({RESUME_REQUESTER, TERMINAL_HANDOFF})
_DEFAULT_CHECKPOINT = (
    "Return to the requester assignment after the launch approval settles."
)


def normalize_requester_continuation(
    value: object,
    *,
    requester: Mapping[str, str],
    reason: str,
    prompt: str,
) -> dict[str, Any]:
    """Return a durable requester-continuation contract for this launch."""

    raw = _mapping_or_none(value, field="requester_continuation")
    context = _clean_context(requester)
    default_mode = RESUME_REQUESTER if context.get("SASE_AGENT") else TERMINAL_HANDOFF
    mode = str(raw.get("mode") or default_mode) if raw is not None else default_mode
    if mode not in _VALID_MODES:
        raise LaunchRequestError(
            "invalid_request",
            "requester_continuation.mode",
            "requester_continuation.mode must be 'resume_requester' "
            "or 'terminal_handoff'",
        )
    if mode == RESUME_REQUESTER and not context.get("SASE_AGENT"):
        raise LaunchRequestError(
            "invalid_request",
            "requester_continuation.mode",
            "resume_requester requires an active agent context",
        )

    checkpoint = _checkpoint(raw, reason=reason)
    required = _required(raw, mode=mode)
    if mode == RESUME_REQUESTER and not required:
        raise LaunchRequestError(
            "invalid_request",
            "requester_continuation.required",
            "resume_requester continuations must be required",
        )
    if mode == RESUME_REQUESTER and _launch_targets_requester_family_lane(
        prompt, context
    ):
        raise LaunchRequestError(
            "conflicting_continuation",
            "requester_continuation.mode",
            "launch prompt targets the requester's family lane while the "
            "requester continuation would also claim that lane; set "
            "requester_continuation.mode='terminal_handoff' or target a "
            "different family",
        )
    if mode == TERMINAL_HANDOFF and required:
        raise LaunchRequestError(
            "invalid_request",
            "requester_continuation.required",
            "terminal_handoff cannot require a requester continuation",
        )

    return {
        "schema_version": LAUNCH_REQUESTER_CONTINUATION_SCHEMA_VERSION,
        "mode": mode,
        "required": required,
        "checkpoint": checkpoint,
        "context": context,
        "resume_branches": list(RESUMING_BRANCHES if mode == RESUME_REQUESTER else ()),
        "terminal_branches": list(
            TERMINAL_BRANCHES
            if mode == RESUME_REQUESTER
            else (*RESUMING_BRANCHES, *TERMINAL_BRANCHES)
        ),
    }


def requester_continuation_note(request: Mapping[str, Any]) -> str:
    """Return a short presentation note for a launch request's continuation."""

    continuation = request.get("requester_continuation")
    if not isinstance(continuation, Mapping):
        return "Requester continuation: not recorded"
    mode = str(continuation.get("mode") or "")
    if mode == RESUME_REQUESTER:
        branches = ", ".join(
            str(branch) for branch in continuation.get("resume_branches") or []
        )
        return f"Requester continuation: resume after {branches or 'settlement'}"
    if mode == TERMINAL_HANDOFF:
        return "Requester continuation: terminal handoff"
    return f"Requester continuation: {mode or 'unknown'}"


def launch_shell_branch_prompt(branch: str, request: Mapping[str, Any]) -> str | None:
    """Return the branch prompt sentinel used by gate-shell settlement."""

    continuation = request.get("requester_continuation")
    if not isinstance(continuation, Mapping):
        return None
    if continuation.get("mode") != RESUME_REQUESTER:
        return None
    if branch not in {str(item) for item in continuation.get("resume_branches") or []}:
        return None
    return (
        "Continue the original requester after this LaunchApproval gate "
        f"settles on {branch}."
    )


def _mapping_or_none(value: object, *, field: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise LaunchRequestError(
            "invalid_request", field, f"{field} must be an object when provided"
        )
    return value


def _checkpoint(raw: Mapping[str, Any] | None, *, reason: str) -> str:
    value = None if raw is None else raw.get("checkpoint")
    if value is None:
        value = reason.strip() or _DEFAULT_CHECKPOINT
    if not isinstance(value, str) or not value.strip():
        raise LaunchRequestError(
            "invalid_request",
            "requester_continuation.checkpoint",
            "requester_continuation.checkpoint must be a non-empty string",
        )
    return value.strip()


def _required(raw: Mapping[str, Any] | None, *, mode: str) -> bool:
    value = None if raw is None else raw.get("required")
    if value is None:
        return mode == RESUME_REQUESTER
    if not isinstance(value, bool):
        raise LaunchRequestError(
            "invalid_request",
            "requester_continuation.required",
            "requester_continuation.required must be a boolean",
        )
    return value


def _clean_context(context: Mapping[str, str]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in context.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        key = key.strip()
        value = value.strip()
        if key and value:
            clean[key] = value
    return clean


def _launch_targets_requester_family_lane(
    prompt: str, context: Mapping[str, str]
) -> bool:
    try:
        from sase.agent.family_attach import extract_family_attach_directive
    except Exception:
        return False

    directive = extract_family_attach_directive(prompt)
    if directive is None:
        return False
    parent = directive.parent.strip()
    if parent == "parent":
        return bool(_requester_family_identity(context))
    family = _requester_family_identity(context)
    return bool(family and parent == family)


def _requester_family_identity(context: Mapping[str, str]) -> str | None:
    family = context.get("agent_meta.agent_family")
    if family:
        return family
    name = context.get("agent_meta.name") or context.get("SASE_AGENT_NAME")
    if not name:
        return None
    try:
        from sase.plan_chain import agent_family_base
    except Exception:
        return name
    return agent_family_base(name) or name


__all__ = [
    "LAUNCH_REQUESTER_CONTINUATION_SCHEMA_VERSION",
    "RESUME_REQUESTER",
    "TERMINAL_HANDOFF",
    "launch_shell_branch_prompt",
    "normalize_requester_continuation",
    "requester_continuation_note",
]

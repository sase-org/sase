"""Exactly-once snapshot-verified release recovery: restart and dismiss.

Keep-work recovery (escalate/continue/instruct) relaunches in the same
workspace; this module owns the releasing side. A restart claims the
resolution, verifies (or refreshes) the recovery snapshot, then runs the
existing restart planner and executor: same raw prompt, same name, fresh
workspace. Restart with a replacement prompt (the Edit backend) runs the
Dismiss transaction, then a normal launch of the given prompt. A dismiss
claims the resolution, verifies the snapshot, then runs the existing
ownership-checked dismiss and releases the bead claim, as a kill does.

Snapshot verification lives in :mod:`sase.agent.hijack._release_snapshot`,
post-snapshot effects in :mod:`sase.agent.hijack._release_effects`, and
settlement in :mod:`sase.agent.hijack._release_settle`. Rust owns the ledger
state machine; this module owns the claim/dispatch order.
``begin_resolution`` accepts restart/dismiss actions, and
``complete_resolution`` settles a dismiss-action record to ``dismissed``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._release_effects import (
    ReleaseEffectDeps,
    dismiss_resolved,
    restart_resolved,
)
from sase.agent.hijack._release_snapshot import ensure_recovery_snapshot
from sase.agent.hijack.core import strip_hijack_launch_directives
from sase.agent.hijack.recover_common import (
    RESULT_ALREADY_RESOLVED,
    RESULT_ALREADY_RESOLVING,
    RESULT_ERROR,
    RESULT_LAUNCHED,
    RESULT_QUEUED,
    RESULT_REFUSED,
    RESULT_UNCERTAIN,
    RecoveryRefusal,
    RecoveryResult,
    RecoverySubject,
    clean_string,
    code_detail,
    current_resolution_result,
    fail_to_held,
    record_revision,
    reload_record,
    reload_resolution,
    resolver_identity,
)
from sase.agent.hijack.recover_subject import load_recovery_subject

LOG = logging.getLogger(__name__)

RELEASE_ACTIONS = frozenset({"restart", "dismiss"})

_RELEASE_FROM_STATES = frozenset({"held", "expired"})


@dataclass
class ReleaseDeps:
    """Injectable seams for the release recovery executor."""

    load_subject: Callable[[object], RecoverySubject | None] | None = None
    preview: Callable[[Mapping[str, Any]], Any] | None = None
    snapshot: Callable[..., list[dict[str, Any]]] | None = None
    plan_restart: Callable[..., Any] | None = None
    execute_restart: Callable[..., Any] | None = None
    dismiss_row: Callable[..., Any] | None = None
    plan_replacement_reuse: Callable[..., Any] | None = None
    apply_replacement_reuse: Callable[..., Any] | None = None
    launch_replacement: Callable[..., Any] | None = None
    release_bead_claim: Callable[[Mapping[str, Any]], tuple[bool, str]] | None = None


def recover_release_action(
    agent_or_name: object,
    *,
    action: str,
    prompt: str | None = None,
    discard_without_snapshot: bool = False,
    expected_hijack_id: str | None = None,
    expected_revision: int | None = None,
    deps: ReleaseDeps | None = None,
) -> RecoveryResult:
    """Execute one exactly-once snapshot-verified release resolution.

    Validates the action and preview availability before any ledger mutation,
    CASes ``held|expired`` to ``resolving``, verifies the recovery snapshot,
    runs the release effect, and settles. Repeat calls report the current
    resolution without acting twice.
    """
    seams = deps or ReleaseDeps()
    load_subject = seams.load_subject or _default_load_subject
    try:
        subject = load_subject(agent_or_name)
    except Exception as exc:
        return RecoveryResult(
            kind=RESULT_ERROR, message=f"Could not load the hijack record: {exc}"
        )
    if subject is None:
        return RecoveryResult(
            kind=RESULT_REFUSED,
            detail=code_detail("record_not_found"),
            message="No hijack recovery record was found",
        )
    record = dict(subject.record)
    hijack_id = clean_string(record.get("hijack_id")) or ""
    revision = record_revision(record)
    if expected_hijack_id is not None and expected_hijack_id != hijack_id:
        return RecoveryResult(
            kind=RESULT_REFUSED,
            hijack_id=hijack_id,
            revision=revision,
            message="The expected hijack id does not match this record",
            detail={
                **code_detail("hijack_mismatch"),
                "expected_hijack_id": expected_hijack_id,
            },
        )
    normalized = clean_string(action) or ""
    if normalized not in RELEASE_ACTIONS:
        return RecoveryResult(
            kind=RESULT_REFUSED,
            hijack_id=hijack_id,
            revision=revision,
            message=(
                f"Release action must be one of {', '.join(sorted(RELEASE_ACTIONS))}, "
                f"got {action!r}"
            ),
            detail=code_detail("unsupported_action"),
        )
    if prompt is not None and normalized != "restart":
        return RecoveryResult(
            kind=RESULT_REFUSED,
            hijack_id=hijack_id,
            revision=revision,
            message="A replacement prompt is supported only with action restart",
            detail=code_detail("incompatible_options"),
        )
    state = clean_string(record.get("state")) or ""
    if state in ("resolved", "dismissed"):
        return current_resolution_result(record, RESULT_ALREADY_RESOLVED)
    if state == "resolving":
        return current_resolution_result(record, RESULT_ALREADY_RESOLVING)
    if state not in _RELEASE_FROM_STATES:
        return RecoveryResult(
            kind=RESULT_REFUSED,
            hijack_id=hijack_id,
            revision=revision,
            message=(f"Release recovery is unavailable while state is {state!r}"),
            detail={**code_detail("not_held"), "state": state},
        )
    try:
        return _release_held(
            subject,
            record,
            hijack_id,
            revision,
            action=normalized,
            prompt=prompt,
            discard_without_snapshot=discard_without_snapshot,
            expected_revision=expected_revision,
            seams=seams,
        )
    except RecoveryRefusal as exc:
        return RecoveryResult(
            kind=RESULT_REFUSED,
            detail=code_detail(exc.code),
            hijack_id=hijack_id,
            message=exc.message,
        )


def _release_held(
    subject: RecoverySubject,
    record: dict[str, Any],
    hijack_id: str,
    revision: int,
    *,
    action: str,
    prompt: str | None,
    discard_without_snapshot: bool,
    expected_revision: int | None,
    seams: ReleaseDeps,
) -> RecoveryResult:
    preview_fn = seams.preview or _default_preview
    try:
        preview = preview_fn(record)
    except Exception as exc:
        raise RecoveryRefusal(
            "preview_error", f"Could not preview release recovery: {exc}"
        ) from exc
    if expected_revision is not None and int(preview.revision) != expected_revision:
        raise RecoveryRefusal(
            "stale_revision",
            f"Preview revision {expected_revision} is stale; the record is "
            f"at revision {int(preview.revision)}",
        )
    row_name = "edit" if (action == "restart" and prompt is not None) else action
    row = preview.action(row_name)
    if row is None or not row.available:
        reason = clean_string(getattr(row, "reason", None)) if row is not None else None
        raise RecoveryRefusal(
            "action_unavailable",
            f"Release action {action!r} is unavailable"
            + (f": {reason}" if reason else ""),
        )
    replacement = _validated_replacement(prompt) if prompt is not None else None
    if clean_string(subject.done_outcome) not in (None, "", "hijacked", "HIJACKED"):
        if str(subject.done_outcome).strip().lower() != "hijacked":
            raise RecoveryRefusal(
                "outcome_changed",
                f"The predecessor outcome is {subject.done_outcome!r}, not "
                "hijacked; a release resolution must not rewrite its marker",
            )
    resolver_pid, resolver_token = resolver_identity()
    begin_event: dict[str, Any] = {
        "event": "begin_resolution",
        "action": row_name,
        "resolver_pid": resolver_pid,
    }
    if action == "restart" and prompt is None:
        begin_event["reserved_successor_name"] = clean_string(record.get("agent_name"))
    if resolver_token:
        begin_event["resolver_process_identity_token"] = resolver_token
    try:
        resolving = dict(ledger.cas_advance_record(record, begin_event))
    except ledger.HijackLedgerConflict:
        return reload_resolution(hijack_id, revision)
    except ValueError as exc:
        raise RecoveryRefusal(
            "ledger_rejected", f"The release reservation was rejected: {exc}"
        ) from exc
    snapshot_fn = seams.snapshot or ensure_recovery_snapshot
    try:
        snapshot_fn(resolving, discard_without_snapshot=discard_without_snapshot)
    except RecoveryRefusal as exc:
        fail_to_held(resolving, exc.message)
        current = reload_record(hijack_id, resolving)
        return RecoveryResult(
            kind=RESULT_ERROR,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action=action,
            successor=None,
            message=exc.message,
            detail={**code_detail(exc.code)},
        )
    effects = ReleaseEffectDeps(
        dismiss_row=seams.dismiss_row,
        plan_restart=seams.plan_restart,
        execute_restart=seams.execute_restart,
        plan_replacement_reuse=seams.plan_replacement_reuse,
        apply_replacement_reuse=seams.apply_replacement_reuse,
        launch_replacement=seams.launch_replacement,
        release_bead_claim=seams.release_bead_claim,
    )
    if action == "dismiss":
        return dismiss_resolved(resolving, deps=effects)
    return restart_resolved(resolving, replacement_prompt=replacement, deps=effects)


def _validated_replacement(prompt: str) -> str:
    """Validate an Edit replacement prompt before any ledger mutation."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise RecoveryRefusal("missing_prompt", "The replacement prompt is empty")
    conflicts = restart_replacement_conflicts(prompt)
    if conflicts:
        raise RecoveryRefusal(
            "conflicting_directives",
            "Replacement prompt carries directives owned by recovery: "
            + ", ".join(conflicts),
        )
    return prompt


def restart_replacement_conflicts(prompt: str) -> list[str]:
    """Return recovery-owned directives in an Edit replacement prompt.

    A changed ``%id`` works through the normal launch path, so it is allowed;
    every other launch-owned directive (placement, waits, budgets, typed or
    fan-out branches) still conflicts, as does a prompt with no task content
    outside its launch directives. Unknown ``%model`` aliases fail closed in
    the directive parser itself before this list is built.
    """
    from sase.agent.hijack.recover_target import conflicting_launch_directives

    try:
        cleaned = strip_hijack_launch_directives(prompt)
    except Exception as exc:
        raise RecoveryRefusal(
            "invalid_prompt", f"Replacement prompt directives do not parse: {exc}"
        ) from exc
    conflicts = [
        item for item in conflicting_launch_directives(prompt) if item != "%id identity"
    ]
    if not cleaned.strip():
        conflicts.insert(0, "prompt has no task content outside launch directives")
    return conflicts


def restart_availability_reason(record: Mapping[str, Any]) -> str | None:
    """Return ``None`` when a plain restart can be planned, else the reason.

    Planner refusals (fan-out, multi-segment, container, disabled provider,
    missing prompt) become the preview's disabled-row reason.
    """
    agent_name = clean_string(record.get("agent_name"))
    if not agent_name:
        return "the hijacked agent name is unknown"
    try:
        _default_plan_restart(agent_name)
    except Exception as exc:
        reason = clean_string(getattr(exc, "reason", None))
        message = clean_string(getattr(exc, "message", None)) or str(exc)
        if reason:
            return f"{reason}: {message}"
        return message
    return None


def _default_load_subject(agent_or_name: object) -> RecoverySubject | None:
    return load_recovery_subject(agent_or_name)


def _default_preview(record: Mapping[str, Any]) -> Any:
    from sase.agent.hijack import preview

    return preview.hijack_recovery_preview(dict(record))


def _default_plan_restart(name: str) -> Any:
    from sase.agent._restart_planning import plan_agent_restart

    return plan_agent_restart(name)


__all__ = [
    "RELEASE_ACTIONS",
    "ReleaseDeps",
    "recover_release_action",
    "restart_availability_reason",
    "restart_replacement_conflicts",
]

"""Applying and repairing hijack latches at verified boundaries."""

from __future__ import annotations

from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._latch_common import (
    application_pending,
    apply_lock_path,
    observe_record,
    owner_identity_for,
    result,
    same_owner,
    same_owner_anchor,
    state_result,
    normalize_suppressed_followup,
)
from sase.agent.hijack._stop_claim import (
    apply_latched_settlement,
    pin_claim,
    remove_intent,
    unpin_claim,
)
from sase.agent.hijack._stop_evidence import collect_and_attach_evidence
from sase.agent.hijack._stop_models import HijackTarget, StopDeps
from sase.agent.hijack.locks import acquire_hijack_lock, record_lock_hold


def apply_latch_at_boundary(
    target_key: str,
    boundary: str,
    boundary_outcome: str,
    *,
    target: HijackTarget,
    deps: StopDeps | None = None,
    suppressed_followup: dict[str, Any] | None = None,
    forced: bool = False,
) -> dict[str, Any]:
    """Apply a latch once the verified owner reaches a safe boundary.

    The per-record apply lock serializes effect replay. The ledger transition
    to ``stopping`` wins against cancel before claim, marker, or snapshot work
    starts; after that point retries finish the same operation and retain the
    numbered claim on every failure.
    """
    deps = deps or StopDeps()
    if not boundary.strip() or not boundary_outcome.strip():
        return result(
            "refused",
            code="boundary_missing",
            message="a safe boundary and its real outcome are required before applying a latch",
            target_key=target_key,
        )
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None:
        return result(
            "no_latch",
            code="no_latch",
            message="there is no active hijack latch for this target",
            target_key=target_key,
        )
    if not same_owner(
        record,
        target,
        owner_identity_for(target),
        target_key=target_key,
    ):
        return result(
            "ownership_uncertain",
            code="owner_identity_mismatch",
            message="the boundary caller is not the member and process that requested this latch; retain custody",
            record=record,
        )
    hijack_id = str(record.get("hijack_id") or "")
    if not hijack_id:
        return result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the active latch record has no operation identity; retain custody",
            record=record,
        )

    lock_path = apply_lock_path(hijack_id)
    with acquire_hijack_lock("apply", lock_path, timeout=30.0):
        current = ledger.load_record(hijack_id)
        if current is None:
            return result(
                "ownership_uncertain",
                code="record_missing",
                message="the latch record disappeared before application; retain custody",
                target_key=target_key,
            )
        observed = observe_record(
            current,
            target_key=target_key,
            boundary=boundary,
            target=target,
        )
        verdict = str(observed.get("verdict") or "")
        if verdict not in {"pending", "applied"}:
            return observed
        if forced and current.get("state") == "latched":
            return result(
                "refused",
                code="force_stop_required",
                message="forced latch application must terminate the identity-matched owner before publishing HIJACKED",
                record=current,
                next_action="use force_hijack_latch after the 120-second eligibility check",
            )

        if current.get("state") == "latched":
            event: dict[str, Any] = {
                "event": ledger.HIJACK_EVENT_APPLY_LATCH,
                "boundary": boundary,
                "boundary_outcome": boundary_outcome,
                "forced": forced,
            }
            normalized_followup = normalize_suppressed_followup(suppressed_followup)
            if normalized_followup is not None:
                event["suppressed_followup"] = normalized_followup
            try:
                current = ledger.cas_advance_record(current, event)
            except ledger.HijackLedgerConflict:
                current = ledger.load_record(hijack_id) or current
                observed = observe_record(
                    current,
                    target_key=target_key,
                    boundary=boundary,
                    target=target,
                )
                if observed.get("verdict") != "applied":
                    return observed

        return complete_latch_application(
            current,
            target,
            target_key=target_key,
            boundary=boundary,
            deps=deps,
        )


def complete_latch_application(
    current: dict[str, Any],
    target: HijackTarget,
    *,
    target_key: str,
    boundary: str,
    deps: StopDeps,
) -> dict[str, Any]:
    """Finish an already-owned latch application while its apply lock is held."""
    hijack_id = str(current.get("hijack_id") or "")
    if not hijack_id:
        return result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the active latch record has no operation identity; retain custody",
            record=current,
        )
    if current.get("state") == "held":
        return state_result(current, target_key)
    if current.get("state") != "stopping" or current.get("latched_at") is None:
        return state_result(current, target_key)

    with record_lock_hold("patch_lock"):
        if not pin_claim(target):
            return application_pending(
                current,
                "claim_mismatch",
                "the exact numbered workspace claim could not be held; no done marker was rewritten",
            )
    try:
        apply_latched_settlement(target, hijack_id)
    except Exception as exc:  # noqa: BLE001 - custody stays pinned for repair.
        return application_pending(
            current,
            "settlement_failed",
            f"the hijacked done marker was not durably written: {exc}",
        )

    existing_snapshots = current.get("snapshots")
    if not isinstance(existing_snapshots, list):
        existing_snapshots = []
    updated, evidence_error, snapshot_error = collect_and_attach_evidence(
        hijack_id,
        target,
        deps=deps,
        existing_snapshots=existing_snapshots,
    )
    current = updated or ledger.load_record(hijack_id) or current
    if evidence_error or snapshot_error:
        code = "snapshot_pending" if snapshot_error else "evidence_pending"
        detail = snapshot_error or evidence_error or "evidence is not durable"
        return application_pending(
            current,
            code,
            f"workspace custody remains held until required evidence is durable: {detail}",
        )
    try:
        held = ledger.cas_advance_record(current, {"event": "confirmed_stop"})
    except Exception as exc:  # noqa: BLE001 - retain stopping custody.
        return application_pending(
            ledger.load_record(hijack_id) or current,
            "publish_failed",
            f"evidence is durable but the held state could not be published: {exc}",
        )
    return observe_record(
        held,
        target_key=target_key,
        boundary=boundary,
        target=target,
        owner_identity=str(current.get("owner_identity") or "") or None,
    )


def apply_reconciled_latch(
    target_key: str,
    *,
    target: HijackTarget,
    boundary_outcome: str,
    deps: StopDeps | None = None,
    suppressed_followup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair a latch only after Rust has proved its owner dead and no successor won."""
    deps = deps or StopDeps()
    active = ledger.find_active_record_by_target_key(target_key)
    hijack_id = str(active.get("hijack_id") or "") if active else ""
    if not hijack_id:
        return result(
            "no_latch",
            code="no_latch",
            message="there is no active latch to reconcile",
            target_key=target_key,
        )
    with acquire_hijack_lock("apply", apply_lock_path(hijack_id), timeout=30.0):
        current = ledger.load_record(hijack_id)
        if current is None or str(current.get("target_key") or "") != target_key:
            return result(
                "ownership_uncertain",
                code="record_missing",
                message="the latch changed before recovery could apply it; retain custody",
                target_key=target_key,
            )
        if not same_owner_anchor(current, target, target_key=target_key):
            return result(
                "ownership_uncertain",
                code="owner_identity_mismatch",
                message="the recovery claim does not match the latch owner identity; retain custody",
                record=current,
            )
        if current.get("state") not in {"latched", "stopping"}:
            return state_result(current, target_key)
        hijack_id = str(current.get("hijack_id") or "")
        if not hijack_id:
            return result(
                "ownership_uncertain",
                code="hijack_id_missing",
                message="the latch record has no operation identity; retain custody",
                record=current,
            )

        from sase.agent._user_kill_intent import (
            has_user_kill_intent,
            hijack_intent_id,
            write_user_kill_intent,
        )
        from sase.agent.hijack._stop_orchestrator_common import (
            build_stop_blocked_result,
            terminate_with_retry,
        )

        created_intent = False
        if has_user_kill_intent(target.artifacts_dir):
            if hijack_intent_id(target.artifacts_dir) != hijack_id:
                return result(
                    "ownership_uncertain",
                    code="intent_conflict",
                    message="a different user-kill intent owns this member; retain custody",
                    record=current,
                )
        else:
            written = write_user_kill_intent(
                target.artifacts_dir,
                pid=int(target.pid or 0),
                source="agent_hijack",
                reason="reconciling a dead owner for a pending hijack latch",
                mode="hijack",
                hijack_id=hijack_id,
            )
            if written is None:
                return result(
                    "ownership_uncertain",
                    code="intent_write_failed",
                    message="the recovery intent could not be durably written; no process was signalled",
                    record=current,
                )
            created_intent = True

        pinned_by_us = not bool(target.claim_pinned)
        with record_lock_hold("patch_lock"):
            if not pin_claim(target):
                if created_intent:
                    remove_intent(target.artifacts_dir)
                return application_pending(
                    current,
                    "claim_mismatch",
                    "the exact numbered workspace claim could not be held; no process was signalled",
                )

        if current.get("state") == "latched":
            event: dict[str, Any] = {
                "event": ledger.HIJACK_EVENT_APPLY_LATCH,
                "boundary": "owner_recovery",
                "boundary_outcome": boundary_outcome,
                "forced": False,
            }
            normalized = normalize_suppressed_followup(suppressed_followup)
            if normalized is not None:
                event["suppressed_followup"] = normalized
            try:
                current = ledger.cas_advance_record(current, event)
            except Exception:
                current = ledger.load_record(hijack_id) or current
                if current.get("state") not in {"stopping", "held"}:
                    if created_intent:
                        remove_intent(target.artifacts_dir)
                    if pinned_by_us:
                        unpin_claim(target)
                    return application_pending(
                        current,
                        "latch_transition_failed",
                        "the dead-owner latch could not enter stopping; custody remains held",
                    )
        if current.get("state") not in {"stopping", "held"}:
            return state_result(current, target_key)
        if current.get("state") == "stopping":
            try:
                termination = terminate_with_retry(target, deps=deps)
            except Exception as exc:  # noqa: BLE001 - retain stopping custody.
                return application_pending(
                    current,
                    "termination_uncertain",
                    f"dead-owner process cleanup is uncertain; workspace remains held: {exc}",
                )
            if not bool(getattr(termination, "success", False)):
                subject = type(
                    "ReconciledSubject",
                    (),
                    {"occupant_name": target.name, "occupant_reason": "dead_owner"},
                )()
                blocked = build_stop_blocked_result(
                    target.name,
                    hijack_id,
                    current,
                    termination,
                    subject=subject,
                    target=target,
                )
                return result(
                    "applied",
                    code="stop_blocked",
                    message=blocked.message,
                    record=blocked.record,
                    target_key=target_key,
                    next_action="retry the stop with ,k, or explicitly release with x",
                    survivor_pids=list(getattr(termination, "survivors", ()) or ()),
                )
        return complete_latch_application(
            current,
            target,
            target_key=target_key,
            boundary=str(current.get("boundary") or "owner_recovery"),
            deps=deps,
        )

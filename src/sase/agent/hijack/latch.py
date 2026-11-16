"""Target-indexed durable Agent Hijack latch primitives.

Rust owns transition, observation, reconciliation, and force policy. This
module coordinates the ledger, target index, workspace claim, done marker,
and evidence files that make a latch durable.
"""

from __future__ import annotations

import time
import uuid
import math
from pathlib import Path
from typing import Any

from sase.agent.hijack import core, ledger
from sase.agent.hijack._stop_claim import (
    apply_latched_settlement,
    pin_claim,
    remove_intent,
    unpin_claim,
)
from sase.agent.hijack._stop_evidence import collect_and_attach_evidence
from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_json_dict
from sase.agent.hijack.locks import acquire_hijack_lock, record_lock_hold


def request_latch(
    name: str,
    *,
    deps: StopDeps | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Create or coalesce one latch for the currently occupying local member.

    The target-index lock covers the second occupant resolution, reservation,
    record creation, and transition to ``latched``. A later turn that reuses a
    session name or PID cannot inherit this request because member, artifact,
    and process identities must all match.
    """
    deps = deps or StopDeps()
    from sase.agent.hijack.facts import resolve_hijack_subject

    subject = resolve_hijack_subject(name, deps=deps)
    target = subject.target
    refusal = _validate_target(subject, target)
    if refusal is not None:
        return refusal
    assert target is not None
    owner_identity = owner_identity_for(target)
    if not owner_identity:
        return _result(
            "ownership_uncertain",
            code="owner_identity_unavailable",
            message="the current owner process identity could not be verified; no latch was written",
        )
    target_key = _target_key(subject, target)
    new_id = hijack_id or _new_hijack_id(target.name)

    with acquire_hijack_lock(
        "target_index", ledger.target_index_lock_path(), timeout=10.0
    ):
        active = ledger.find_active_record_by_target_key(target_key)
        if active is not None:
            if not _same_owner(active, target, owner_identity, target_key=target_key):
                return _result(
                    "ownership_uncertain",
                    code="target_owner_changed",
                    message="this target key is reserved by a different member or process identity; retain custody and inspect the active record",
                    record=active,
                )
            return _observe_record(
                active,
                target_key=target_key,
                boundary="request",
                target=target,
            )

        winner = ledger.claim_target_slot_locked(target_key, new_id)
        if winner != new_id:
            active = ledger.load_record(winner)
            if active is not None:
                if not _same_owner(
                    active, target, owner_identity, target_key=target_key
                ):
                    return _result(
                        "ownership_uncertain",
                        code="target_owner_changed",
                        message="the winning target reservation belongs to a different member or process identity",
                        record=active,
                    )
                return _observe_record(
                    active,
                    target_key=target_key,
                    boundary="request",
                    target=target,
                )
            return _result(
                "ownership_uncertain",
                code="target_reservation_uncertain",
                message="a target reservation exists but its record cannot be read; retain custody",
            )

        fresh_subject = resolve_hijack_subject(name, deps=deps)
        fresh_target = fresh_subject.target
        fresh_refusal = _validate_target(fresh_subject, fresh_target)
        fresh_identity = (
            None if fresh_target is None else owner_identity_for(fresh_target)
        )
        if (
            fresh_refusal is not None
            or fresh_target is None
            or fresh_subject.occupant_name != subject.occupant_name
            or _target_identity(fresh_target) != _target_identity(target)
            or fresh_identity != owner_identity
            or _target_key(fresh_subject, fresh_target) != target_key
        ):
            ledger.release_target_slot_locked(target_key, new_id)
            return _result(
                "ownership_uncertain",
                code="occupant_changed",
                message="the occupying member or process identity changed while reserving the latch; nothing was applied",
            )

        target = fresh_target
        record = ledger.new_requested_record(
            hijack_id=new_id,
            agent_name=target.name,
            artifacts_dir=target.artifacts_dir,
            pid=target.pid,
            process_identity_token=owner_identity,
            project_file=None if target.is_home else target.project_file,
            workspace_num=target.workspace_num,
            workspace_dir=target.workspace_dir,
            expected_claim_owner_pid=target.claim_pid,
            session=target.agent_session,
            target_key=target_key,
            scope="llm",
        )
        record["prior_pin_state"] = bool(target.claim_pinned)
        created = False
        try:
            ledger.create_record(record)
            created = True
            latched = ledger.cas_advance_record(
                record,
                {
                    "event": ledger.HIJACK_EVENT_LATCH,
                    "owner_pid": int(target.pid or 0),
                    "owner_identity": owner_identity,
                    "latched_at": math.ceil(current_time(deps) * 1_000),
                },
            )
        except Exception as exc:
            if created:
                try:
                    ledger.hijack_record_path(new_id).unlink(missing_ok=True)
                except OSError:
                    pass
            ledger.release_target_slot_locked(target_key, new_id)
            return _result(
                "error",
                code="latch_request_failed",
                message=f"could not durably request the hijack latch: {exc}",
            )
        return _observe_record(
            latched,
            target_key=target_key,
            boundary="request",
            target=target,
        )


def observe_hijack_latch(
    target_key: str,
    boundary: str,
    *,
    member: str | None = None,
    artifacts_dir: str | None = None,
    owner_pid: int | None = None,
    owner_identity: str | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Return a Rust-validated latch verdict for one target and boundary."""
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None and hijack_id:
        record = ledger.load_record(hijack_id)
    if record is None or str(record.get("target_key") or "") != target_key:
        return _result(
            "no_latch",
            code="no_latch",
            message="there is no active hijack latch for this target",
            target_key=target_key,
        )
    if record.get("latched_at") is None and record.get("state") != "cancelled":
        return _result(
            "no_latch",
            code="no_latch",
            message="the target has no latch operation",
            record=record,
            target_key=target_key,
        )
    facts = {
        "schema_version": core.agent_hijack_latch_wire_schema_version(),
        "target_key": target_key,
        "boundary": boundary,
        "member": member or "",
        "artifacts_dir": artifacts_dir or "",
        "owner_pid": owner_pid,
        "owner_identity": owner_identity,
    }
    return core.agent_hijack_latch_observe(record, facts)


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
        return _result(
            "refused",
            code="boundary_missing",
            message="a safe boundary and its real outcome are required before applying a latch",
            target_key=target_key,
        )
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None:
        return _result(
            "no_latch",
            code="no_latch",
            message="there is no active hijack latch for this target",
            target_key=target_key,
        )
    if not _same_owner(
        record,
        target,
        owner_identity_for(target),
        target_key=target_key,
    ):
        return _result(
            "ownership_uncertain",
            code="owner_identity_mismatch",
            message="the boundary caller is not the member and process that requested this latch; retain custody",
            record=record,
        )
    hijack_id = str(record.get("hijack_id") or "")
    if not hijack_id:
        return _result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the active latch record has no operation identity; retain custody",
            record=record,
        )

    lock_path = _apply_lock_path(hijack_id)
    with acquire_hijack_lock("apply", lock_path, timeout=30.0):
        current = ledger.load_record(hijack_id)
        if current is None:
            return _result(
                "ownership_uncertain",
                code="record_missing",
                message="the latch record disappeared before application; retain custody",
                target_key=target_key,
            )
        observed = _observe_record(
            current,
            target_key=target_key,
            boundary=boundary,
            target=target,
        )
        verdict = str(observed.get("verdict") or "")
        if verdict not in {"pending", "applied"}:
            return observed
        if forced and current.get("state") == "latched":
            return _result(
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
            normalized_followup = _suppressed_followup(suppressed_followup)
            if normalized_followup is not None:
                event["suppressed_followup"] = normalized_followup
            try:
                current = ledger.cas_advance_record(current, event)
            except ledger.HijackLedgerConflict:
                current = ledger.load_record(hijack_id) or current
                observed = _observe_record(
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
        return _result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the active latch record has no operation identity; retain custody",
            record=current,
        )
    if current.get("state") == "held":
        return _state_result(current, target_key)
    if current.get("state") != "stopping" or current.get("latched_at") is None:
        return _state_result(current, target_key)

    with record_lock_hold("patch_lock"):
        if not pin_claim(target):
            return _application_pending(
                current,
                "claim_mismatch",
                "the exact numbered workspace claim could not be held; no done marker was rewritten",
            )
    try:
        apply_latched_settlement(target, hijack_id)
    except Exception as exc:  # noqa: BLE001 - custody stays pinned for repair.
        return _application_pending(
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
        return _application_pending(
            current,
            code,
            f"workspace custody remains held until required evidence is durable: {detail}",
        )
    try:
        held = ledger.cas_advance_record(current, {"event": "confirmed_stop"})
    except Exception as exc:  # noqa: BLE001 - retain stopping custody.
        return _application_pending(
            ledger.load_record(hijack_id) or current,
            "publish_failed",
            f"evidence is durable but the held state could not be published: {exc}",
        )
    return _observe_record(
        held,
        target_key=target_key,
        boundary=boundary,
        target=target,
        owner_identity=str(current.get("owner_identity") or "") or None,
    )


def cancel_latch(
    target_key: str,
    *,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Cancel only a still-pending latch; application races return their winner."""
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None and hijack_id:
        record = ledger.load_record(hijack_id)
    if record is None or str(record.get("target_key") or "") != target_key:
        return _result(
            "no_latch",
            code="no_latch",
            message="there is no latch to cancel",
            target_key=target_key,
        )
    if record.get("latched_at") is None and record.get("state") != "cancelled":
        return _result(
            "no_latch",
            code="no_latch",
            message="the target has no latch operation",
            record=record,
            target_key=target_key,
        )
    hijack_id_value = record.get("hijack_id")
    if not isinstance(hijack_id_value, str) or not hijack_id_value:
        return _result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the latch record has no operation identity; retain custody",
            record=record,
        )
    with acquire_hijack_lock("apply", _apply_lock_path(hijack_id_value)):
        current = ledger.load_record(hijack_id_value) or record
        if (
            str(current.get("target_key") or "") != target_key
            or current.get("state") != "latched"
        ):
            return _state_result(current, target_key)
        try:
            cancelled = ledger.cas_advance_record(
                current, {"event": ledger.HIJACK_EVENT_CANCEL_LATCH}
            )
        except ledger.HijackLedgerConflict:
            cancelled = ledger.load_record(hijack_id_value) or current
        return _state_result(cancelled, target_key)


def moot_latch(
    target_key: str,
    boundary: str,
    boundary_outcome: str,
    *,
    target: HijackTarget,
    suppressed_followup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Release a pending target reservation when the owner finishes normally."""
    if not boundary.strip() or not boundary_outcome.strip():
        return _result(
            "refused",
            code="boundary_missing",
            message="a real terminal outcome and boundary are required to moot a latch",
            target_key=target_key,
        )
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None:
        return _result(
            "no_latch",
            code="no_latch",
            message="there is no latch to moot",
            target_key=target_key,
        )
    if not same_owner_anchor(record, target, target_key=target_key):
        return _result(
            "ownership_uncertain",
            code="owner_identity_mismatch",
            message="the terminal outcome does not match the member, artifact directory, process id, and target key that requested this latch",
            record=record,
        )
    recorded_identity = str(record.get("owner_identity") or "").strip()
    if not recorded_identity:
        return _result(
            "ownership_uncertain",
            code="owner_identity_missing",
            message="the latch has no recorded process identity; retain custody",
            record=record,
        )
    hijack_id = str(record.get("hijack_id") or "")
    if not hijack_id:
        return _result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the latch record has no operation identity; retain custody",
            record=record,
        )
    with acquire_hijack_lock("apply", _apply_lock_path(hijack_id)):
        current = ledger.load_record(hijack_id) or record
        if not same_owner_anchor(current, target, target_key=target_key):
            return _result(
                "ownership_uncertain",
                code="owner_identity_mismatch",
                message="the terminal outcome does not match the latch owner; retain custody",
                record=current,
            )
        observed = _observe_record(
            current,
            target_key=target_key,
            boundary=boundary,
            target=target,
            owner_identity=recorded_identity,
        )
        if observed.get("verdict") != "pending":
            return observed
        event: dict[str, Any] = {
            "event": ledger.HIJACK_EVENT_MOOT_LATCH,
            "boundary": boundary,
            "boundary_outcome": boundary_outcome,
        }
        normalized_followup = _suppressed_followup(suppressed_followup)
        if normalized_followup is not None:
            event["suppressed_followup"] = normalized_followup
        try:
            finished = ledger.cas_advance_record(current, event)
        except ledger.HijackLedgerConflict:
            finished = ledger.load_record(hijack_id) or current
        return _state_result(finished, target_key)


def force_hijack_latch(
    target_key: str,
    *,
    deps: StopDeps | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Explicitly interrupt a live latch owner after Rust's 120-second bound."""
    from sase.agent.hijack._latch_force import force_hijack_latch as force

    return force(target_key, deps=deps, hijack_id=hijack_id)


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
        return _result(
            "no_latch",
            code="no_latch",
            message="there is no active latch to reconcile",
            target_key=target_key,
        )
    with acquire_hijack_lock("apply", _apply_lock_path(hijack_id), timeout=30.0):
        current = ledger.load_record(hijack_id)
        if current is None or str(current.get("target_key") or "") != target_key:
            return _result(
                "ownership_uncertain",
                code="record_missing",
                message="the latch changed before recovery could apply it; retain custody",
                target_key=target_key,
            )
        if not same_owner_anchor(current, target, target_key=target_key):
            return _result(
                "ownership_uncertain",
                code="owner_identity_mismatch",
                message="the recovery claim does not match the latch owner identity; retain custody",
                record=current,
            )
        if current.get("state") not in {"latched", "stopping"}:
            return _state_result(current, target_key)
        hijack_id = str(current.get("hijack_id") or "")
        if not hijack_id:
            return _result(
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
                return _result(
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
                return _result(
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
                return _application_pending(
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
            normalized = _suppressed_followup(suppressed_followup)
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
                    return _application_pending(
                        current,
                        "latch_transition_failed",
                        "the dead-owner latch could not enter stopping; custody remains held",
                    )
        if current.get("state") not in {"stopping", "held"}:
            return _state_result(current, target_key)
        if current.get("state") == "stopping":
            try:
                termination = terminate_with_retry(target, deps=deps)
            except Exception as exc:  # noqa: BLE001 - retain stopping custody.
                return _application_pending(
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
                return _result(
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


def _validate_target(
    subject: Any, target: HijackTarget | None
) -> dict[str, Any] | None:
    if (
        target is None
        or subject.is_remote
        or subject.is_bulk
        or subject.is_named_proc
        or subject.is_clan_container
        or (target is not None and (target.is_monitor_turn or target.is_gate_turn))
    ):
        return _result(
            "refused",
            code="unsupported_target",
            message="a latch requires a local, directly addressable agent member",
        )
    if (
        target.is_home
        or target.workspace_num is None
        or target.claim_pid is None
        or target.pid is None
    ):
        return _result(
            "refused",
            code="numbered_claim_required",
            message="a latch requires a live member with an exact numbered workspace claim",
        )
    selected = subject.selected
    if selected is None or selected.settled or not selected.process_alive:
        return _result(
            "refused",
            code="owner_not_live",
            message="the selected member is no longer a live owner; no latch was written",
        )
    if "hijack" not in target.capabilities:
        return _result(
            "refused",
            code="hijack_capability_required",
            message="the selected member does not advertise hijack capability",
        )
    return None


def _target_key(subject: Any, target: HijackTarget) -> str:
    session = getattr(subject, "session", None)
    base_name = getattr(session, "base_name", None)
    owner_name = base_name or target.agent_session or target.name
    project_file = None if target.is_home else target.project_file
    return ledger.target_key_for(project_file, str(owner_name))


def _target_identity(target: HijackTarget) -> tuple[Any, ...]:
    return (
        target.name,
        target.project_file,
        target.artifacts_timestamp,
        target.artifacts_dir,
        target.pid,
        target.claim_pid,
        target.workspace_num,
        target.agent_session,
        target.is_home,
    )


def _same_owner(
    record: dict[str, Any],
    target: HijackTarget,
    identity: str | None,
    *,
    target_key: str,
) -> bool:
    return (
        same_owner_anchor(record, target, target_key=target_key)
        and bool(identity)
        and str(record.get("owner_identity") or "") == identity
    )


def same_owner_anchor(
    record: dict[str, Any],
    target: HijackTarget,
    *,
    target_key: str,
) -> bool:
    return (
        str(record.get("agent_name") or "") == target.name
        and str(record.get("artifacts_dir") or "") == target.artifacts_dir
        and record.get("owner_pid") == target.pid
        and str(record.get("target_key") or "") == target_key
    )


def owner_identity_for(target: HijackTarget) -> str | None:
    if target.pid is None or target.pid <= 0:
        return None
    metadata = read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
    recorded = metadata.get("process_identity")
    recorded_identity = recorded.strip() if isinstance(recorded, str) else ""
    try:
        from sase.core.process_identity import process_identity_token

        current = process_identity_token(int(target.pid))
    except (OSError, RuntimeError, ValueError):
        current = ""
    if not current or (recorded_identity and current != recorded_identity):
        return None
    return current


def _observe_record(
    record: dict[str, Any],
    *,
    target_key: str,
    boundary: str,
    target: HijackTarget,
    owner_identity: str | None = None,
) -> dict[str, Any]:
    identity = owner_identity or owner_identity_for(target)
    return core.agent_hijack_latch_observe(
        record,
        {
            "schema_version": core.agent_hijack_latch_wire_schema_version(),
            "target_key": target_key,
            "boundary": boundary,
            "member": target.name,
            "artifacts_dir": target.artifacts_dir,
            "owner_pid": target.pid,
            "owner_identity": identity,
        },
    )


def _state_result(record: dict[str, Any], target_key: str) -> dict[str, Any]:
    state = str(record.get("state") or "")
    verdict = {
        "latched": "pending",
        "stopping": "applied" if record.get("latched_at") is not None else "no_latch",
        "held": "applied" if record.get("latched_at") is not None else "no_latch",
        "cancelled": "cancelled",
        "finished_first": "moot"
        if record.get("latched_at") is not None
        else "no_latch",
    }.get(state, "no_latch")
    return _result(
        verdict,
        code=state or "no_latch",
        message=f"hijack latch is {state or 'absent'}",
        record=record,
        target_key=target_key,
    )


def _application_pending(
    record: dict[str, Any], code: str, message: str
) -> dict[str, Any]:
    hijack_id = str(record.get("hijack_id") or "")
    if hijack_id:
        try:
            ledger.merge_record_fields(hijack_id, {"error": message})
            record = ledger.load_record(hijack_id) or record
        except Exception:
            pass
    return _result(
        "applied",
        code=code,
        message=message,
        record=record,
        target_key=str(record.get("target_key") or ""),
        ready=False,
    )


def _suppressed_followup(
    followup: dict[str, Any] | None,
) -> dict[str, str] | None:
    if not isinstance(followup, dict):
        return None
    kind = followup.get("kind")
    reference = followup.get("ref", followup.get("reference"))
    if not isinstance(kind, str) or not kind.strip():
        return None
    if not isinstance(reference, str) or not reference.strip():
        return None
    return {"kind": kind.strip(), "ref": reference.strip()}


def _result(
    verdict: str,
    *,
    code: str,
    message: str,
    record: dict[str, Any] | None = None,
    target_key: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "code": code,
        "message": message,
        "hijack_id": None if record is None else record.get("hijack_id"),
        "target_key": target_key
        or (None if record is None else record.get("target_key")),
        "record": record,
        **fields,
    }


def current_time(deps: StopDeps) -> float:
    return float(deps.now() if deps.now is not None else time.time())


def _new_hijack_id(name: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in name
    ).strip("_")
    return f"hijack-{cleaned or 'agent'}-{uuid.uuid4().hex[:12]}"


def _apply_lock_path(hijack_id: str) -> Path:
    return ledger.hijack_record_path(hijack_id).with_suffix(".apply.lock")


__all__ = [
    "apply_reconciled_latch",
    "apply_latch_at_boundary",
    "cancel_latch",
    "complete_latch_application",
    "current_time",
    "force_hijack_latch",
    "moot_latch",
    "owner_identity_for",
    "observe_hijack_latch",
    "request_latch",
    "same_owner_anchor",
]

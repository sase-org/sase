"""Observing, canceling, and mooting hijack latch requests."""

from __future__ import annotations

from typing import Any

from sase.agent.hijack import core, ledger
from sase.agent.hijack._latch_common import (
    apply_lock_path,
    observe_record,
    result,
    same_owner_anchor,
    state_result,
    normalize_suppressed_followup,
)
from sase.agent.hijack._stop_models import HijackTarget
from sase.agent.hijack.locks import acquire_hijack_lock


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
        return result(
            "no_latch",
            code="no_latch",
            message="there is no active hijack latch for this target",
            target_key=target_key,
        )
    if record.get("latched_at") is None and record.get("state") != "cancelled":
        return result(
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
        return result(
            "no_latch",
            code="no_latch",
            message="there is no latch to cancel",
            target_key=target_key,
        )
    if record.get("latched_at") is None and record.get("state") != "cancelled":
        return result(
            "no_latch",
            code="no_latch",
            message="the target has no latch operation",
            record=record,
            target_key=target_key,
        )
    hijack_id_value = record.get("hijack_id")
    if not isinstance(hijack_id_value, str) or not hijack_id_value:
        return result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the latch record has no operation identity; retain custody",
            record=record,
        )
    with acquire_hijack_lock("apply", apply_lock_path(hijack_id_value)):
        current = ledger.load_record(hijack_id_value) or record
        if (
            str(current.get("target_key") or "") != target_key
            or current.get("state") != "latched"
        ):
            return state_result(current, target_key)
        try:
            cancelled = ledger.cas_advance_record(
                current, {"event": ledger.HIJACK_EVENT_CANCEL_LATCH}
            )
        except ledger.HijackLedgerConflict:
            cancelled = ledger.load_record(hijack_id_value) or current
        return state_result(cancelled, target_key)


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
        return result(
            "refused",
            code="boundary_missing",
            message="a real terminal outcome and boundary are required to moot a latch",
            target_key=target_key,
        )
    record = ledger.find_active_record_by_target_key(target_key)
    if record is None:
        return result(
            "no_latch",
            code="no_latch",
            message="there is no latch to moot",
            target_key=target_key,
        )
    if not same_owner_anchor(record, target, target_key=target_key):
        return result(
            "ownership_uncertain",
            code="owner_identity_mismatch",
            message="the terminal outcome does not match the member, artifact directory, process id, and target key that requested this latch",
            record=record,
        )
    recorded_identity = str(record.get("owner_identity") or "").strip()
    if not recorded_identity:
        return result(
            "ownership_uncertain",
            code="owner_identity_missing",
            message="the latch has no recorded process identity; retain custody",
            record=record,
        )
    hijack_id = str(record.get("hijack_id") or "")
    if not hijack_id:
        return result(
            "ownership_uncertain",
            code="hijack_id_missing",
            message="the latch record has no operation identity; retain custody",
            record=record,
        )
    with acquire_hijack_lock("apply", apply_lock_path(hijack_id)):
        current = ledger.load_record(hijack_id) or record
        if not same_owner_anchor(current, target, target_key=target_key):
            return result(
                "ownership_uncertain",
                code="owner_identity_mismatch",
                message="the terminal outcome does not match the latch owner; retain custody",
                record=current,
            )
        observed = observe_record(
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
        normalized_followup = normalize_suppressed_followup(suppressed_followup)
        if normalized_followup is not None:
            event["suppressed_followup"] = normalized_followup
        try:
            finished = ledger.cas_advance_record(current, event)
        except ledger.HijackLedgerConflict:
            finished = ledger.load_record(hijack_id) or current
        return state_result(finished, target_key)

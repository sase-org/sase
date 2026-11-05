"""Observe, resume, and cancel recovery admission requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._recovery_admission_common import (
    LOGICAL_ID,
    bundle_dir_for_request,
    descriptor_from_data,
    read_prepared_recovery_descriptor,
    record_owns_descriptor,
    required_string,
    string_or_none,
    validate_request_id,
)
from sase.agent.hijack._recovery_admission_dispatch import (
    dispatch_recovery_admission,
)
from sase.agent.launch_admission_store import (
    RECEIPT_FILENAME,
    admission_dir,
    read_journal,
    read_json,
)

__all__ = [
    "cancel_recovery_admission_for_rollback",
    "cancel_recovery_admission_request",
    "observe_recovery_admission",
    "resume_recovery_admission",
]


def observe_recovery_admission(request_id: str) -> dict[str, Any]:
    """Read request and journal status for recovery reconciliation callers."""
    from sase.agent.launch_request_response import read_launch_request

    validate_request_id(request_id)
    bundle_dir = bundle_dir_for_request(request_id)
    try:
        data = read_launch_request(bundle_dir)
    except Exception as exc:
        return {
            "request_id": request_id,
            "state": "missing",
            "message": str(exc),
        }
    descriptor = descriptor_from_data(data)
    plan_digest = str(data.get("plan_digest") or "")
    states = _ledgerless_admission_states(bundle_dir)
    logical_id = str((descriptor or {}).get("logical_id") or LOGICAL_ID)
    unit_state = states.get(logical_id, {})
    phase = str(unit_state.get("phase") or "submitted")
    return {
        "request_id": request_id,
        "dispatch_fingerprint": str(
            (descriptor or {}).get("dispatch_fingerprint") or ""
        ),
        "identity": unit_state.get("identity"),
        "plan_digest": plan_digest,
        "state": phase,
        "message": unit_state.get("message"),
        "receipt_state": unit_state.get("receipt_state"),
        "in_flight": phase
        in {"submitted", "reserved", "waiting", "checking", "eligible", "dispatching"},
        "cancel_requested": (admission_dir(bundle_dir) / "cancel.json").is_file(),
        "receipt": read_json(admission_dir(bundle_dir) / RECEIPT_FILENAME),
    }


def resume_recovery_admission(
    record: Mapping[str, Any],
    *,
    spawn_successor: Callable[..., Any] | None = None,
    resolve_session_plan: Callable[[str, str | None], Any] | None = None,
) -> dict[str, Any]:
    """Resume the exact pending request after a resolver interruption."""
    from sase.agent.launch_request_response import read_launch_request

    request_id = string_or_none(record.get("admission_request_id"))
    if request_id is None:
        return {"state": "missing", "message": "record has no admission request id"}
    descriptor = read_prepared_recovery_descriptor(request_id)
    bundle_dir = bundle_dir_for_request(request_id)
    if descriptor is None:
        try:
            descriptor = descriptor_from_data(read_launch_request(bundle_dir))
        except Exception:
            descriptor = None
    if descriptor is None:
        return observe_recovery_admission(request_id)
    if not record_owns_descriptor(record, descriptor):
        return {
            "request_id": request_id,
            "state": "mismatch",
            "message": "prepared request does not match the resolving reservation",
        }
    status = observe_recovery_admission(request_id)
    if status.get("state") not in {
        "missing",
        "submitted",
        "reserved",
        "waiting",
        "eligible",
    }:
        return status
    try:
        dispatch_recovery_admission(
            descriptor,
            spawn_successor=spawn_successor,
            resolve_session_plan=resolve_session_plan,
            spawn_coordinator=True,
        )
    except Exception as exc:  # noqa: BLE001 - retain attempt for reconciliation
        status = observe_recovery_admission(request_id)
        status["message"] = f"could not resume durable recovery request: {exc}"
        return status
    return observe_recovery_admission(request_id)


def cancel_recovery_admission_request(
    request_id: str,
    *,
    reason: str = "recovery attempt cancelled",
) -> dict[str, Any]:
    """Durably cancel one request and wait until its admission journal settles."""
    from sase.agent.hijack.recover_common import fail_to_held
    from sase.agent.launch_admission import cancel_typed_launch_request
    from sase.agent.launch_request_response import read_launch_request

    validate_request_id(request_id)
    bundle_dir = bundle_dir_for_request(request_id)
    result = cancel_typed_launch_request(
        bundle_dir,
        reason=reason,
    )
    if result.get("state") != "cancelled":
        return result
    try:
        descriptor = descriptor_from_data(read_launch_request(bundle_dir))
    except Exception:
        descriptor = None
    if descriptor is None:
        return result
    current = ledger.load_record(required_string(descriptor, "hijack_id"))
    if current is None or not record_owns_descriptor(current, descriptor):
        return result
    fail_to_held(current, reason)
    settled = ledger.load_record(required_string(descriptor, "hijack_id"))
    result["recovery_state"] = (
        str(settled.get("state") or "unknown")
        if isinstance(settled, Mapping)
        else "unknown"
    )
    return result


def cancel_recovery_admission_for_rollback(
    request_id: str,
    *,
    reason: str = "recovery confirmation failed",
) -> dict[str, Any]:
    """Make a recovery request non-dispatchable without changing its bead state.

    Confirmation rollback must first prove cancellation, child termination,
    and custody restoration, then advance the hijack record. The ordinary
    cancellation entrypoint also returns the record to held, so this variant
    deliberately performs only the admission cancellation and observation.
    """
    status = observe_recovery_admission(request_id)
    if not status.get("in_flight"):
        return dict(status)

    from sase.agent.launch_admission import cancel_typed_launch_request

    try:
        cancellation = cancel_typed_launch_request(
            bundle_dir_for_request(request_id), reason=reason
        )
    except Exception as exc:  # noqa: BLE001 - observe whether cancellation settled
        status = observe_recovery_admission(request_id)
        return {
            **dict(status),
            "cancel_error": str(exc),
        }
    status = observe_recovery_admission(request_id)
    return {
        **dict(status),
        "cancellation": dict(cancellation),
    }


def _ledgerless_admission_states(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    """Return the latest typed admission states without mutating the journal."""
    from sase.core.agent_launch_facade import reconcile_admission_journal

    return reconcile_admission_journal(read_journal(admission_dir(bundle_dir)))

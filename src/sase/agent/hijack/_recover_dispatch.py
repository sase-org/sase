"""Dispatch and settle a previously prepared hijack recovery."""

from __future__ import annotations

import logging
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_common import (
    RESULT_ERROR,
    RESULT_QUEUED,
    RESULT_UNCERTAIN,
    RecoveryDeps,
    RecoveryRefusal,
    RecoveryResult,
    clean_string,
    fail_to_held,
    record_launch_stage,
    record_revision,
    reload_record,
    reload_resolution,
)
from sase.agent.hijack.recover_confirm import confirm_and_settle
from sase.agent.hijack.recovery_admission import (
    dispatch_recovery_admission,
    remove_prepared_recovery_descriptor,
)
from sase.agent.hijack._recover_prepare import PreparedRecovery
from sase.agent.hijack._recover_prepare import validate_pinned_target

LOG = logging.getLogger(__name__)


def dispatch_held_recovery(
    prepared: PreparedRecovery,
    *,
    goal: str | None,
    bead: str | None,
    seams: RecoveryDeps,
) -> RecoveryResult:
    """CAS the reservation, dispatch admission, then confirm and settle."""
    subject = prepared.subject
    record = prepared.record
    hijack_id = prepared.hijack_id
    revision = prepared.revision
    target = prepared.target
    reserved_name = prepared.reserved_name
    resolver_pid = prepared.resolver_pid
    resolver_token = prepared.resolver_token
    launch_identity = prepared.launch_identity
    request_id = prepared.request_id
    binding = prepared.binding
    descriptor = prepared.descriptor
    begin_event: dict[str, Any] = {
        "event": "begin_resolution",
        "action": target.action,
        "reserved_successor_name": reserved_name,
        "concrete_target_model": target.concrete_target,
        "model_changed": target.model_changed,
        "resolver_pid": resolver_pid,
        "launch_identity": launch_identity,
        "admission_request_id": binding["admission_request_id"],
        "admission_identity": binding["admission_identity"],
    }
    if resolver_token:
        begin_event["resolver_process_identity_token"] = resolver_token
    try:
        resolving = dict(ledger.cas_advance_record(record, begin_event))
    except ledger.HijackLedgerConflict:
        remove_prepared_recovery_descriptor(request_id)
        return reload_resolution(hijack_id, revision)
    except ValueError as exc:
        remove_prepared_recovery_descriptor(request_id)
        raise RecoveryRefusal(
            "ledger_rejected",
            f"The recovery reservation was rejected: {exc}",
        ) from exc

    record_launch_event: dict[str, Any] = {
        "event": "record_launch",
        "launch_identity": launch_identity,
        "admission_request_id": binding["admission_request_id"],
        "admission_identity": binding["admission_identity"],
        "launch_stage": "prepared",
    }
    try:
        resolving = dict(ledger.cas_advance_record(resolving, record_launch_event))
    except ledger.HijackLedgerConflict:
        current = reload_record(hijack_id, resolving)
        if current.get("admission_request_id") != request_id:
            remove_prepared_recovery_descriptor(request_id)
        return reload_resolution(hijack_id, record_revision(resolving))
    except ValueError as exc:
        message = f"The admission binding was rejected: {exc}"
        remove_prepared_recovery_descriptor(request_id)
        fail_to_held(resolving, message)
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) != "held":
            return RecoveryResult(
                kind=RESULT_UNCERTAIN,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action=target.action,
                successor=reserved_name,
                launch_identity=launch_identity,
                admission_request_id=request_id,
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=(
                    "The admission binding was rejected, but the reservation "
                    "could not be returned to held"
                ),
                detail={"launch_stage": "failed"},
            )
        raise RecoveryRefusal(
            "ledger_rejected",
            message,
        ) from exc

    try:
        validate_pinned_target(resolving, target, mode="dispatch", seams=seams)
    except RecoveryRefusal as exc:
        remove_prepared_recovery_descriptor(request_id)
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) != "held":
            return RecoveryResult(
                kind=RESULT_UNCERTAIN,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action=target.action,
                successor=reserved_name,
                launch_identity=launch_identity,
                admission_request_id=request_id,
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=(
                    "Pinned target validation failed before dispatch, but the "
                    f"reservation remains resolving: {exc.message}"
                ),
                detail={"code": exc.code, "launch_stage": "failed"},
            )
        raise

    try:
        admission_result, _bundle_dir = dispatch_recovery_admission(
            descriptor,
            spawn_successor=seams.spawn_successor,
            resolve_session_plan=seams.resolve_session_plan,
            spawn_coordinator=seams.admission_spawn_coordinator,
        )
    except Exception as exc:  # noqa: BLE001 - request may already dispatch
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="dispatching",
            error=f"uncertain admission outcome: {exc}",
        )
        LOG.warning("uncertain recovery admission for %s: %s", hijack_id, exc)
        current = reload_record(hijack_id, resolving)
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "The durable recovery request may still dispatch; the record "
                f"retains resolving for reconciliation: {exc}"
            ),
            detail={"launch_stage": "dispatching"},
        )

    unit_result = next(
        (
            item
            for item in admission_result.unit_results
            if item.logical_id == str(descriptor["logical_id"])
        ),
        None,
    )
    if not admission_result.admission_complete:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="queued",
            error=unit_result.message if unit_result is not None else None,
        )
        current = reload_record(hijack_id, resolving)
        return RecoveryResult(
            kind=RESULT_QUEUED,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                unit_result.message
                if unit_result is not None and unit_result.message
                else "Recovery is queued in durable launch admission"
            ),
            detail={"launch_stage": "queued", "admission_state": "queued"},
        )

    if unit_result is None or unit_result.outcome != "launched":
        message = (
            unit_result.message
            if unit_result is not None and unit_result.message
            else "The recovery admission request did not launch its unit"
        )
        # A terminal admission journal cannot dispatch this attempt later.
        fail_to_held(resolving, message)
        current = reload_record(hijack_id, resolving)
        if clean_string(current.get("state")) != "held":
            return RecoveryResult(
                kind=RESULT_UNCERTAIN,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action=target.action,
                successor=reserved_name,
                launch_identity=launch_identity,
                admission_request_id=request_id,
                concrete_target=target.concrete_target,
                model_changed=target.model_changed,
                message=(
                    "Admission is terminal but the recovery reservation could "
                    "not be returned to held"
                ),
                detail={
                    "launch_stage": "failed",
                    "admission_state": (
                        unit_result.outcome if unit_result is not None else "unknown"
                    ),
                },
            )
        remove_prepared_recovery_descriptor(request_id)
        return RecoveryResult(
            kind=RESULT_ERROR,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=message,
            detail={
                "code": "launch_failed",
                "launch_stage": "failed",
                "admission_state": (
                    unit_result.outcome if unit_result is not None else "unknown"
                ),
            },
        )

    if not admission_result.results:
        current = reload_record(hijack_id, resolving)
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "Admission journal says launched but returned no child observation"
            ),
            detail={"launch_stage": "dispatching", "admission_state": "launched"},
        )

    resolving = reload_record(hijack_id, resolving)
    return confirm_and_settle(
        resolving,
        subject=subject,
        hijack_id=hijack_id,
        target=target,
        reserved_name=reserved_name,
        launch_identity=launch_identity,
        binding=binding,
        launched=admission_result.results[0],
        context_mode=target.context_mode,
        goal=goal,
        bead=bead,
        seams=seams,
    )

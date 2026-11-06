"""Exactly-once keep-work recovery launch and settlement.

Phase ``resolution_launch`` of the keep-work recovery child epic: compose the
CAS resolution transaction with normal admission, reserved successor
identity, strict spawning, rollback, lineage, and predecessor settlement.

The transaction order is fixed:

1. Load the hijack record and a fresh read-only preview. Refusals (unknown
   record, unavailable action, stale preview revision, bad model) happen
   before any ledger mutation.
2. Compute the complete reservation (action, reserved successor name,
   concrete target, resolver identity, durable launch identity, admission
   binding) and CAS ``held`` to ``resolving``. Concurrent resolvers yield
   exactly one winner; losers return the winner's current resolution.
3. Persist the admission binding with a ``record_launch`` event *before*
   dispatch so a resolver crash leaves durable evidence for reconciliation.
4. Dispatch through the strict successor seam
   (:mod:`sase.agent.hijack.recovery_successor`). Revalidate the pinned
   model before dispatch. Definite pre-launch failures return the record to
   ``held`` with an error; uncertain post-spawn outcomes retain
   ``resolving`` and custody for reconciliation.
5. Confirm successor identity, workspace claim, inheritance
   acknowledgement, and effective model, then CAS ``complete_resolution``
   and settle the predecessor ``done.json``. Settlement is idempotent so
   the reconcile phase can repair an interrupted write.

Rust owns state transitions and the preview/reconcile policy; this module
owns Python effects. There is no parallel Python state machine.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.hijack.recover_common import (
    KEEP_WORK_ACTIONS,
    RECOVERY_LAUNCH_IDENTITY_ENV,
    RESULT_ALREADY_RESOLVED,
    RESULT_ALREADY_RESOLVING,
    RESULT_ERROR,
    RESULT_LAUNCHED,
    RESULT_QUEUED,
    RESULT_REFUSED,
    RESULT_UNCERTAIN,
    TERMINAL_RECOVERY_STATES,
    InheritanceEvidence,
    RecoveryDeps,
    RecoveryRefusal,
    RecoveryResult,
    RecoverySubject,
    RecoveryTarget,
    admission_binding_for,
    clean_string,
    code_detail,
    current_resolution_result,
    new_launch_identity,
    predecessor_concrete_target,
    record_revision,
    resolver_identity,
    reload_record,
)
from sase.agent.hijack.recover_confirm import successor_holds_claim
from sase.agent.hijack.recover_settle import (
    gather_recovery_inheritance,
    settle_recovery,
)
from sase.agent.hijack.recover_subject import (
    lineage_for,
    load_recovery_subject,
    session_base_for,
)
from sase.agent.hijack.recovery_admission import (
    remove_prepared_recovery_descriptor,
    resume_recovery_admission,
)
from sase.agent.hijack.recover_target import (
    conflicting_launch_directives,
    extract_prompt_model,
    require_concrete_target,
    resolve_effective_target,
)
from sase.agent.hijack._recover_dispatch import (
    dispatch_held_recovery as _dispatch_held_recovery,
)
from sase.agent.hijack._recover_prepare import (
    prepare_held_recovery as _prepare_held_recovery,
)


def recover_hijacked_agent(
    agent_or_name: object,
    *,
    action: str,
    model: str | None = None,
    prompt: str | None = None,
    expected_hijack_id: str | None = None,
    expected_revision: int | None = None,
    goal: str | None = None,
    bead: str | None = None,
    deps: RecoveryDeps | None = None,
) -> RecoveryResult:
    """Execute one exactly-once keep-work recovery.

    Validates the action and effective target against a fresh preview,
    CASes ``held`` to ``resolving`` with the complete reservation, binds
    the durable admission request before dispatch, spawns through the
    strict successor seam, then confirms and settles. Returns a structured
    result distinguishing refusal, queued recovery, confirmed launch, and
    error; the successor identity is included whenever one is known.
    Repeat calls return the current resolution without launching again.
    """
    seams = deps or RecoveryDeps()
    load_subject = seams.load_subject or load_recovery_subject
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
    state = clean_string(record.get("state")) or ""
    if state == "resolved":
        try:
            from sase.agent.hijack.recover_reconcile import repair_settled_projection

            repair_settled_projection(record)
        except Exception:
            pass
        return current_resolution_result(record, RESULT_ALREADY_RESOLVED)
    if state == "resolving":
        if expected_revision is not None and expected_revision != revision:
            result = current_resolution_result(record, RESULT_REFUSED)
            return RecoveryResult(
                kind=result.kind,
                hijack_id=result.hijack_id,
                revision=result.revision,
                action=result.action,
                successor=result.successor,
                launch_identity=result.launch_identity,
                admission_request_id=result.admission_request_id,
                concrete_target=result.concrete_target,
                model_changed=result.model_changed,
                message=(
                    f"Preview revision {expected_revision} is stale; the "
                    f"record is at revision {revision}"
                ),
                detail={**dict(result.detail), "code": "stale_revision"},
            )
        return _resume_existing_resolution(record, seams=seams)
    if state in TERMINAL_RECOVERY_STATES or state != "held":
        return RecoveryResult(
            kind=RESULT_REFUSED,
            hijack_id=hijack_id,
            revision=revision,
            message=(f"Keep-work recovery is unavailable while state is {state!r}"),
            detail={**code_detail("not_held"), "state": state},
        )
    try:
        return _recover_held(
            subject,
            record,
            hijack_id,
            revision,
            action=action,
            model=model,
            prompt=prompt,
            expected_revision=expected_revision,
            goal=goal,
            bead=bead,
            seams=seams,
        )
    except RecoveryRefusal as exc:
        return RecoveryResult(
            kind=RESULT_REFUSED,
            detail=code_detail(exc.code),
            hijack_id=hijack_id,
            message=exc.message,
        )


def _recover_held(
    subject: RecoverySubject,
    record: dict[str, Any],
    hijack_id: str,
    revision: int,
    *,
    action: str,
    model: str | None,
    prompt: str | None,
    expected_revision: int | None,
    goal: str | None,
    bead: str | None,
    seams: RecoveryDeps,
) -> RecoveryResult:
    prepared = _prepare_held_recovery(
        subject,
        record,
        hijack_id,
        revision,
        action=action,
        model=model,
        prompt=prompt,
        expected_revision=expected_revision,
        seams=seams,
    )
    return _dispatch_held_recovery(prepared, goal=goal, bead=bead, seams=seams)


def _resume_existing_resolution(
    record: Mapping[str, Any],
    *,
    seams: RecoveryDeps | None = None,
) -> RecoveryResult:
    """Resume the CAS-bound admission bundle without creating another request.

    The return-to-held decision comes from Rust: when the admission journal
    proves the reserved request never dispatched, reconciliation (via
    ``_reconcile_before_resume`` and the post-resume check below) returns
    the record to held. There is no standalone Python predicate.
    """
    current = dict(record)
    reconciled = _reconcile_before_resume(current, seams=seams)
    if reconciled is not None:
        return reconciled
    result = current_resolution_result(current, RESULT_ALREADY_RESOLVING)
    try:
        observation = resume_recovery_admission(
            current,
            spawn_successor=seams.spawn_successor if seams is not None else None,
            resolve_session_plan=(
                seams.resolve_session_plan if seams is not None else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 - keep the reservation for repair
        observation = {"state": "uncertain", "message": str(exc)}
    if not isinstance(observation, Mapping):
        observation = {"state": "uncertain", "message": str(observation)}
    observation = dict(observation)
    # Route a proven not-dispatched admission through Rust reconciliation so
    # the held decision (including dead-resolver and minimum-age gates) is
    # owned by the core. Uses the single shared observer definition.
    try:
        from sase.agent.hijack._recover_reconcile_observation import (
            admission_proves_not_dispatched,
        )
        from sase.agent.hijack.recover_reconcile import reconcile_recovery

        if admission_proves_not_dispatched(observation):
            rerun = reconcile_recovery(current, deps=seams)
            if isinstance(rerun, Mapping) and str(rerun.get("outcome") or "") == (
                "return_to_held"
            ):
                current = reload_record(str(current.get("hijack_id") or ""), current)
                if clean_string(current.get("state")) == "held":
                    request_id = clean_string(
                        record.get("admission_request_id")
                    ) or clean_string(current.get("admission_request_id"))
                    if request_id:
                        remove_prepared_recovery_descriptor(request_id)
                    return RecoveryResult(
                        kind=RESULT_ERROR,
                        hijack_id=result.hijack_id,
                        revision=record_revision(current),
                        action=result.action,
                        successor=result.successor,
                        launch_identity=result.launch_identity,
                        admission_request_id=result.admission_request_id,
                        concrete_target=result.concrete_target,
                        model_changed=result.model_changed,
                        message=str(
                            rerun.get("message")
                            or observation.get("message")
                            or "recovery admission was never dispatched"
                        ),
                        detail={
                            **dict(result.detail),
                            "admission": dict(observation),
                            "code": str(rerun.get("code") or "not_dispatched"),
                            "launch_stage": str(observation.get("state") or ""),
                            "reconciled": True,
                        },
                    )
    except Exception:
        pass
    phase = str(observation.get("state") or "")
    in_flight = bool(observation.get("in_flight")) or phase in {
        "submitted",
        "reserved",
        "waiting",
        "checking",
        "eligible",
        "dispatching",
        "queued",
    }
    launched = phase in {"launched", "dispatched"} or (
        not in_flight
        and clean_string(observation.get("identity")) is not None
        and not admission_proves_not_dispatched(observation)
        if isinstance(observation, Mapping)
        else False
    )
    if in_flight or phase in {"queued"}:
        return RecoveryResult(
            kind=RESULT_QUEUED,
            hijack_id=result.hijack_id,
            revision=result.revision,
            action=result.action,
            successor=result.successor,
            launch_identity=result.launch_identity,
            admission_request_id=result.admission_request_id,
            concrete_target=result.concrete_target,
            model_changed=result.model_changed,
            message=str(observation.get("message") or result.message),
            detail={**dict(result.detail), "admission": dict(observation)},
        )
    if launched:
        return RecoveryResult(
            kind=RESULT_LAUNCHED,
            hijack_id=result.hijack_id,
            revision=result.revision,
            action=result.action,
            successor=result.successor,
            launch_identity=result.launch_identity,
            admission_request_id=result.admission_request_id,
            concrete_target=result.concrete_target,
            model_changed=result.model_changed,
            message=str(observation.get("message") or result.message),
            detail={**dict(result.detail), "admission": dict(observation)},
        )
    detail = {**dict(result.detail), "admission": dict(observation)}
    # Surface the latest reconcile code/message instead of discarding it.
    try:
        from sase.agent.hijack._recover_reconcile_observation import (
            gather_reconcile_facts,
        )
        from sase.agent.hijack.core import hijack_recovery_reconcile

        facts = gather_reconcile_facts(current, deps=seams)
        decision = hijack_recovery_reconcile(dict(current), dict(facts))
        if isinstance(decision, Mapping):
            detail = {
                **detail,
                "reconcile_outcome": decision.get("outcome"),
                "reconcile_code": decision.get("code"),
                "reconcile_message": decision.get("message"),
            }
    except Exception:
        pass
    return RecoveryResult(
        kind=result.kind,
        hijack_id=result.hijack_id,
        revision=result.revision,
        action=result.action,
        successor=result.successor,
        launch_identity=result.launch_identity,
        admission_request_id=result.admission_request_id,
        concrete_target=result.concrete_target,
        model_changed=result.model_changed,
        message=result.message,
        detail=detail,
    )


def _reconcile_before_resume(
    record: Mapping[str, Any],
    *,
    seams: RecoveryDeps | None = None,
) -> RecoveryResult | None:
    """Run one bounded reconcile before resuming a resolving record.

    Returns a terminal result when reconciliation adopted the proven
    successor or returned the record to held; returns ``None`` when the
    reservation must stay resolving and the caller should resume admission.
    Failures fail closed to ``None`` so a broken observer never releases
    custody or duplicates a launch.
    """
    from sase.agent.hijack.recover_reconcile import reconcile_recovery

    try:
        outcome = reconcile_recovery(record, deps=seams)
    except Exception:
        return None
    action_taken = str(outcome.get("action_taken") or "none")
    decided = outcome.get("record")
    current = (
        dict(decided)
        if isinstance(decided, Mapping) and decided
        else reload_record(str(record.get("hijack_id") or ""), record)
    )
    if action_taken == "adopted":
        return current_resolution_result(current, RESULT_ALREADY_RESOLVED)
    if action_taken == "returned_to_held":
        return RecoveryResult(
            kind=RESULT_ERROR,
            hijack_id=clean_string(current.get("hijack_id")),
            revision=record_revision(current),
            action=clean_string(current.get("resolution_action")),
            successor=clean_string(current.get("reserved_successor_name")),
            launch_identity=clean_string(current.get("launch_identity")),
            admission_request_id=clean_string(current.get("admission_request_id")),
            concrete_target=clean_string(current.get("concrete_target_model")),
            model_changed=current.get("model_changed")
            if isinstance(current.get("model_changed"), bool)
            else None,
            message=str(outcome.get("message") or "Recovery returned to held"),
            detail={
                "code": str(outcome.get("code") or "returned_to_held"),
                "reconciled": True,
            },
        )
    return None


__all__ = [
    "KEEP_WORK_ACTIONS",
    "RECOVERY_LAUNCH_IDENTITY_ENV",
    "RESULT_ALREADY_RESOLVED",
    "RESULT_ALREADY_RESOLVING",
    "RESULT_ERROR",
    "RESULT_LAUNCHED",
    "RESULT_QUEUED",
    "RESULT_REFUSED",
    "RESULT_UNCERTAIN",
    "InheritanceEvidence",
    "RecoveryDeps",
    "RecoveryRefusal",
    "RecoveryResult",
    "RecoverySubject",
    "RecoveryTarget",
    "admission_binding_for",
    "conflicting_launch_directives",
    "extract_prompt_model",
    "gather_recovery_inheritance",
    "lineage_for",
    "load_recovery_subject",
    "new_launch_identity",
    "predecessor_concrete_target",
    "recover_hijacked_agent",
    "require_concrete_target",
    "resolver_identity",
    "resolve_effective_target",
    "session_base_for",
    "settle_recovery",
    "successor_holds_claim",
]

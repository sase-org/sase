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

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack import preview as preview_module
from sase.agent.hijack.core import (
    hijack_recovery_execution_wire_schema_version,
    hijack_recovery_validate_execution,
)
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
    admission_request_id_for,
    clean_string,
    code_detail,
    current_resolution_result,
    fail_to_held,
    new_launch_identity,
    predecessor_concrete_target,
    record_launch_stage,
    record_pid,
    record_revision,
    record_workspace_num,
    resolver_identity,
    reload_record,
    reload_resolution,
)
from sase.agent.hijack.recover_confirm import confirm_and_settle, successor_holds_claim
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
    dispatch_recovery_admission,
    prepare_recovery_admission_descriptor,
    persist_prepared_recovery_descriptor,
    remove_prepared_recovery_descriptor,
    resume_recovery_admission,
)
from sase.agent.hijack.recover_target import (
    conflicting_launch_directives,
    extract_prompt_model,
    require_concrete_target,
    resolve_effective_target,
)
from sase.agent.hijack.recovery_successor import (
    RecoveryInheritanceError,
    RecoveryLineage,
)

LOG = logging.getLogger(__name__)


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
    preview_fn = seams.preview or _default_preview
    try:
        preview = preview_fn(record)
    except preview_module.HijackRecoveryRefusal as exc:
        raise RecoveryRefusal(exc.code, exc.message) from exc
    if expected_revision is not None and expected_revision != int(preview.revision):
        raise RecoveryRefusal(
            "stale_revision",
            f"Preview revision {expected_revision} is stale; the record is "
            f"at revision {int(preview.revision)}",
        )
    row = preview.action(action)
    if row is None:
        raise RecoveryRefusal(
            "unsupported_action",
            f"Recovery action must be one of {', '.join(KEEP_WORK_ACTIONS)}, "
            f"got {action!r}",
        )
    target = resolve_effective_target(
        action=action,
        record=record,
        preview_action={
            "available": row.available,
            "reason": row.reason,
            "target": row.target,
        },
        model_override=model,
        prompt_text=prompt,
    )
    target = _prepare_continuation_target(
        record, target, build_prompt_fn=seams.build_prompt
    )
    _validate_pinned_target(record, target, mode="prepare", seams=seams)
    if clean_string(subject.done_outcome) not in (None, "", "hijacked", "HIJACKED"):
        if str(subject.done_outcome).strip().lower() != "hijacked":
            raise RecoveryRefusal(
                "outcome_changed",
                f"The predecessor outcome is {subject.done_outcome!r}, not "
                "hijacked; recovery must not rewrite its marker",
            )
    session_base = session_base_for(record, subject.predecessor_meta)
    if not session_base:
        raise RecoveryRefusal(
            "no_session",
            "The predecessor has no agent-session parent to attach the "
            "reserved successor to",
        )
    project_name = subject.project_name
    resolve_plan = seams.resolve_session_plan or _default_resolve_session_plan
    try:
        plan = resolve_plan(session_base, project_name)
    except Exception as exc:
        raise RecoveryRefusal(
            "unresolvable_successor",
            f"Could not reserve the recovery successor identity: {exc}",
        ) from exc
    reserved_name = clean_string(getattr(plan, "agent_name", None))
    if not reserved_name:
        raise RecoveryRefusal(
            "unresolvable_successor",
            "The attach resolver produced no reserved successor name",
        )
    workspace_num = record_workspace_num(record)
    workspace_dir = clean_string(record.get("workspace_dir"))
    if workspace_num is None or not workspace_dir:
        raise RecoveryRefusal(
            "workspace_unavailable",
            "Recovery requires the predecessor's fixed positive workspace number "
            "and directory",
        )
    if not project_name:
        raise RecoveryRefusal(
            "unresolvable_successor",
            "Recovery requires the predecessor project name for strict dispatch",
        )
    resolver_pid, resolver_token = resolver_identity()
    launch_identity = new_launch_identity()
    request_id = admission_request_id_for(hijack_id, launch_identity)
    lineage = lineage_for(hijack_id=hijack_id, record=record, target=target)
    from sase.agent.launch_submission import capture_launch_submitted_at

    try:
        descriptor = prepare_recovery_admission_descriptor(
            record=record,
            action=target.action,
            target=target.concrete_target,
            model_changed=target.model_changed,
            prompt=target.prompt,
            context_mode=target.context_mode,
            reserved_successor_name=reserved_name,
            session_base=session_base,
            project_name=project_name,
            launch_identity=launch_identity,
            admission_request_id=request_id,
            lineage=lineage,
            resolver_pid=resolver_pid,
            resolver_process_identity_token=resolver_token,
            # begin_resolution advances the held record once before dispatch.
            attempt_revision=record_revision(record) + 1,
            launch_submitted_at=capture_launch_submitted_at(),
        )
        binding = admission_binding_for(
            hijack_id,
            launch_identity,
            str(descriptor["dispatch_fingerprint"]),
        )
        persist_prepared_recovery_descriptor(descriptor)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RecoveryRefusal(
            "admission_preparation_failed",
            f"Could not prepare the durable recovery request: {exc}",
        ) from exc
    if binding["admission_request_id"] != request_id:
        remove_prepared_recovery_descriptor(request_id)
        raise RecoveryRefusal(
            "admission_preparation_failed",
            "The durable recovery request id changed during preparation",
        )

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
        _validate_pinned_target(resolving, target, mode="dispatch", seams=seams)
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


def _resume_existing_resolution(
    record: Mapping[str, Any],
    *,
    seams: RecoveryDeps | None = None,
) -> RecoveryResult:
    """Resume the CAS-bound admission bundle without creating another request."""
    current = dict(record)
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
    detail = {**dict(result.detail), "admission": dict(observation)}
    phase = str(observation.get("state") or "")
    receipt_state = str(observation.get("receipt_state") or "")
    definitely_not_dispatched = phase == "cancelled" or (
        phase == "launch_error" and receipt_state in {"failed", "rejected"}
    )
    if definitely_not_dispatched:
        message = str(observation.get("message") or "recovery admission was cancelled")
        request_id = clean_string(current.get("admission_request_id"))
        fail_to_held(current, message)
        current = reload_record(str(current.get("hijack_id") or ""), current)
        if clean_string(current.get("state")) == "held":
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
                message=message,
                detail={**detail, "code": "launch_failed", "launch_stage": phase},
            )
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=result.hijack_id,
            revision=record_revision(current),
            action=result.action,
            successor=result.successor,
            launch_identity=result.launch_identity,
            admission_request_id=result.admission_request_id,
            concrete_target=result.concrete_target,
            model_changed=result.model_changed,
            message="Admission is terminal but held custody could not be restored",
            detail=detail,
        )
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


def _default_preview(record: Mapping[str, Any]) -> Any:
    return preview_module.hijack_recovery_preview(dict(record))


def _default_resolve_session_plan(session_base: str, project_name: str | None) -> Any:
    from sase.agent import _agent_session_attach_resolution as resolution
    from sase.agent.detached_child import AgentSessionAttachDirective

    if not project_name:
        raise RecoveryInheritanceError(
            "recovery requires the predecessor project name to resolve the "
            "reserved successor"
        )
    return resolution.resolve_agent_session_attach_plan(
        AgentSessionAttachDirective(parent=session_base, suffix="@"),
        project_name=project_name,
    )


def _validate_pinned_target(
    record: Mapping[str, Any],
    target: RecoveryTarget,
    *,
    mode: str,
    seams: RecoveryDeps,
) -> None:
    """Validate the pinned target without reopening the public preview menu."""
    facts_fn = seams.execution_facts or _default_execution_facts
    try:
        facts = facts_fn(record, target.concrete_target, mode)
        decision = hijack_recovery_validate_execution(
            dict(record), target.concrete_target, facts
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        if mode == "dispatch":
            fail_to_held(dict(record), f"pinned target validation failed: {exc}")
        raise RecoveryRefusal(
            "target_unavailable",
            f"Could not validate the pinned {target.action} target: {exc}",
        ) from exc
    if clean_string(decision.get("outcome")) == "proceed":
        return
    code = clean_string(decision.get("code")) or "target_unavailable"
    message = clean_string(decision.get("message")) or (
        f"The pinned {target.action} target is not available for {mode}"
    )
    if mode == "dispatch":
        fail_to_held(dict(record), f"pinned target revalidation: {message}")
    raise RecoveryRefusal(code, message)


def _prepare_continuation_target(
    held: Mapping[str, Any],
    target: RecoveryTarget,
    *,
    build_prompt_fn: Callable[..., Any] | None = None,
) -> RecoveryTarget:
    """Prepare prompt text while the record is still in the held state."""
    if target.prompt:
        try:
            prepared = preview_module.validate_hijack_continuation_prompt(
                dict(held),
                prompt=target.prompt,
                model_target=target.concrete_target,
            )
        except preview_module.HijackRecoveryRefusal as exc:
            raise RecoveryRefusal(exc.code, exc.message) from exc
        return replace(
            target,
            prompt=prepared.prompt,
            context_mode=prepared.context_mode,
            transcript_path=prepared.transcript_path,
        )
    build = build_prompt_fn or preview_module.build_hijack_continuation_prompt
    try:
        prepared = build(
            dict(held),
            model_target=target.concrete_target,
            guidance_requested=False,
        )
    except preview_module.HijackRecoveryRefusal as exc:
        raise RecoveryRefusal(exc.code, exc.message) from exc
    return replace(
        target,
        prompt=str(prepared.prompt),
        context_mode=str(prepared.context_mode),
        transcript_path=clean_string(getattr(prepared, "transcript_path", None)),
    )


def _default_execution_facts(
    record: Mapping[str, Any], pinned_target: str, mode: str
) -> Mapping[str, Any]:
    """Gather current provider availability and the resolver's identity."""
    from sase.llm_provider.model_alias_resolution_types import (
        resolved_target_is_available,
    )
    from sase.llm_provider.provider_disable_peek import peek_active_provider_disables

    provider, model = _target_provider_model(pinned_target)
    disables = peek_active_provider_disables()
    provider_disabled = provider in disables
    available = False
    reason: str | None = None
    if provider_disabled:
        reason = f"provider {provider!r} is disabled"
    else:
        try:
            available = resolved_target_is_available(
                f"{provider}/{model}", provider_disables=disables
            )
        except Exception as exc:  # noqa: BLE001 - unavailable facts fail closed
            reason = f"could not confirm provider/model availability: {exc}"
        if not available and reason is None:
            reason = f"provider/model {provider}/{model} is unavailable"

    observed_pid, observed_token = resolver_identity()
    expected_pid = record_pid(record.get("resolver_pid"))
    expected_token = clean_string(record.get("resolver_process_identity_token"))
    resolver_pid_live = mode != "dispatch" or observed_pid == expected_pid
    resolver_identity_matches = mode != "dispatch" or (
        observed_pid == expected_pid
        and observed_token is not None
        and expected_token is not None
        and observed_token == expected_token
    )
    return {
        "schema_version": hijack_recovery_execution_wire_schema_version(),
        "observed_resolver_pid": observed_pid if mode == "dispatch" else None,
        "resolver_pid_live": resolver_pid_live,
        "resolver_identity_matches": resolver_identity_matches,
        "pinned_available": available,
        "pinned_unavailable_reason": reason,
        "current_target": pinned_target if available else None,
        "provider_disabled": provider_disabled,
        "model_unavailable": not available and not provider_disabled,
    }


def _target_provider_model(value: str) -> tuple[str, str]:
    base, separator, effort = value.rpartition("@")
    if separator and effort in {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        value = base
    provider, slash, model = value.partition("/")
    if not slash or not provider or not model:
        raise ValueError("pinned target is not provider/model concrete")
    return provider, model


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

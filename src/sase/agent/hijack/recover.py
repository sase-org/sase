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

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack import preview as preview_module
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
        return current_resolution_result(record, RESULT_ALREADY_RESOLVING)
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
    resolver_pid, resolver_token = resolver_identity()
    launch_identity = new_launch_identity()
    binding = admission_binding_for(
        hijack_id, launch_identity, reserved_name, target.concrete_target
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
        return reload_resolution(hijack_id, revision)
    except ValueError as exc:
        raise RecoveryRefusal(
            "ledger_rejected",
            f"The recovery reservation was rejected: {exc}",
        ) from exc
    resolving_revision = record_revision(resolving)
    record_launch_event: dict[str, Any] = {
        "event": "record_launch",
        "launch_identity": launch_identity,
        "admission_request_id": binding["admission_request_id"],
        "admission_identity": binding["admission_identity"],
        "launch_stage": "queued",
    }
    try:
        resolving = dict(ledger.cas_advance_record(resolving, record_launch_event))
    except ledger.HijackLedgerConflict:
        return reload_resolution(hijack_id, resolving_revision)
    except ValueError as exc:
        raise RecoveryRefusal(
            "ledger_rejected",
            f"The admission binding was rejected: {exc}",
        ) from exc
    _revalidate_pinned_target(
        resolving, target, preview_fn=preview_fn, hijack_id=hijack_id
    )
    prompt_text, context_mode = _continuation_prompt_for(
        resolving, target, build_prompt_fn=seams.build_prompt
    )
    spawn_fn = seams.spawn_successor or _default_spawn_successor
    lineage = lineage_for(hijack_id=hijack_id, record=resolving, target=target)
    extra_env = {
        RECOVERY_LAUNCH_IDENTITY_ENV: launch_identity,
    }
    try:
        from sase.agent.hijack.recovery_successor import (
            RECOVERY_LINEAGE_ENV,
            RECOVERY_STRICT_ENV,
        )

        extra_env[RECOVERY_LINEAGE_ENV] = json.dumps(lineage.as_dict(), sort_keys=True)
        extra_env[RECOVERY_STRICT_ENV] = "1"
    except Exception as exc:
        fail_to_held(resolving, f"Could not encode the recovery lineage: {exc}")
        return RecoveryResult(
            kind=RESULT_ERROR,
            detail=code_detail("lineage_error"),
            hijack_id=hijack_id,
            revision=record_revision(resolving),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Could not encode the recovery lineage: {exc}",
        )
    try:
        launched = spawn_fn(
            session_base=session_base,
            plan=plan,
            project_name=project_name,
            prompt=prompt_text,
            workspace_dir=clean_string(resolving.get("workspace_dir")),
            workspace_num=record_workspace_num(resolving),
            transfer_from_pid=record_pid(resolving.get("pid")),
            lineage=lineage,
            extra_env=extra_env,
        )
    except _ClaimQueued as exc:
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="queued",
            error=str(exc),
        )
        return RecoveryResult(
            kind=RESULT_QUEUED,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=str(exc),
            detail={"launch_stage": "queued"},
        )
    except RecoveryInheritanceError as exc:
        fail_to_held(resolving, str(exc))
        return RecoveryResult(
            kind=RESULT_ERROR,
            detail=code_detail("inheritance_failed"),
            hijack_id=hijack_id,
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=str(exc),
        )
    except (RuntimeError, OSError, ValueError) as exc:
        fail_to_held(resolving, str(exc) or type(exc).__name__)
        return RecoveryResult(
            kind=RESULT_ERROR,
            detail=code_detail("launch_failed"),
            hijack_id=hijack_id,
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=f"Recovery launch failed before spawn: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - uncertain post-spawn outcome
        record_launch_stage(
            resolving,
            launch_identity,
            binding,
            stage="prepared",
            error=f"uncertain launch outcome: {exc}",
        )
        LOG.warning("uncertain recovery launch for %s: %s", hijack_id, exc)
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id, resolving)),
            action=target.action,
            successor=reserved_name,
            launch_identity=launch_identity,
            admission_request_id=binding["admission_request_id"],
            concrete_target=target.concrete_target,
            model_changed=target.model_changed,
            message=(
                "The launch outcome is uncertain; the record retains "
                f"resolving and custody for reconciliation: {exc}"
            ),
            detail={"launch_stage": "prepared"},
        )
    return confirm_and_settle(
        resolving,
        subject=subject,
        hijack_id=hijack_id,
        target=target,
        reserved_name=reserved_name,
        launch_identity=launch_identity,
        binding=binding,
        launched=launched,
        context_mode=context_mode,
        goal=goal,
        bead=bead,
        seams=seams,
    )


class _ClaimQueued(RuntimeError):
    """The strict spawn could not proceed yet; the reservation stands."""


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


def _default_spawn_successor(
    *,
    session_base: str,
    plan: Any,
    project_name: str | None,
    prompt: str,
    workspace_dir: str | None,
    workspace_num: int | None,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage,
    extra_env: Mapping[str, str] | None = None,
) -> Any:
    from sase.agent.detached_child import (
        AgentSessionAttachDirective,
        spawn_recovery_successor,
    )
    from sase.running_field import WorkspaceClaimError

    if not project_name:
        raise RecoveryInheritanceError(
            "recovery requires the predecessor project name to spawn"
        )
    if workspace_num is None or not workspace_dir:
        raise RecoveryInheritanceError(
            "recovery requires the held workspace pair to spawn"
        )
    try:
        return spawn_recovery_successor(
            AgentSessionAttachDirective(parent=session_base, suffix="@"),
            project_name=project_name,
            prompt=prompt,
            workspace_dir=workspace_dir,
            workspace_num=int(workspace_num),
            transfer_from_pid=transfer_from_pid,
            lineage=lineage,
            extra_env=dict(extra_env or {}),
            resolve_plan=lambda *args, **kwargs: plan,
        )
    except WorkspaceClaimError as exc:
        raise _ClaimQueued(
            f"Recovery launch is queued on the held workspace: {exc}"
        ) from exc


def _revalidate_pinned_target(
    resolving: Mapping[str, Any],
    target: RecoveryTarget,
    *,
    preview_fn: Callable[[Mapping[str, Any]], Any],
    hijack_id: str,
) -> None:
    """Confirm the pinned target is still available before dispatch.

    A model rotation between the caller's preview and execution fails the
    reservation back to ``held`` with an error instead of launching a
    target nobody previewed.
    """
    try:
        preview = preview_fn(dict(resolving))
    except preview_module.HijackRecoveryRefusal as exc:
        fail_to_held(dict(resolving), f"pinned target revalidation: {exc}")
        raise RecoveryRefusal(
            "target_unavailable",
            f"The pinned {target.action} target is no longer available: {exc.message}",
        ) from exc
    row = preview.action(target.action)
    current = clean_string(row.target if row else None)
    if row is None or not row.available or current != target.concrete_target:
        fail_to_held(
            dict(resolving),
            f"pinned target changed: {current!r} != {target.concrete_target!r}",
        )
        raise RecoveryRefusal(
            "target_unavailable",
            f"The pinned {target.action} target changed before dispatch "
            f"({current!r}); refresh the preview and retry",
        )


def _continuation_prompt_for(
    resolving: Mapping[str, Any],
    target: RecoveryTarget,
    *,
    build_prompt_fn: Callable[..., Any] | None = None,
) -> tuple[str, str]:
    """Return the successor prompt and its context mode."""
    if target.action == "instruct":
        return target.prompt, target.context_mode or "instruct"
    build = build_prompt_fn or preview_module.build_hijack_continuation_prompt
    try:
        prepared = build(
            dict(resolving),
            model_target=target.concrete_target,
            guidance_requested=False,
        )
    except preview_module.HijackRecoveryRefusal as exc:
        fail_to_held(dict(resolving), f"continuation prompt: {exc}")
        raise RecoveryRefusal(exc.code, exc.message) from exc
    return prepared.prompt, prepared.context_mode


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

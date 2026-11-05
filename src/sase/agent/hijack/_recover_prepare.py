"""Prepare a held hijack recovery reservation before dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from sase.agent.hijack import preview as preview_module
from sase.agent.hijack.core import (
    hijack_recovery_execution_wire_schema_version,
    hijack_recovery_validate_execution,
)
from sase.agent.hijack.recover_common import (
    KEEP_WORK_ACTIONS,
    RecoveryDeps,
    RecoveryRefusal,
    RecoverySubject,
    RecoveryTarget,
    admission_binding_for,
    admission_request_id_for,
    clean_string,
    code_detail,
    fail_to_held,
    new_launch_identity,
    record_pid,
    record_revision,
    record_workspace_num,
    resolver_identity,
)
from sase.agent.hijack.recover_subject import lineage_for, session_base_for
from sase.agent.hijack.recovery_admission import (
    prepare_recovery_admission_descriptor,
    persist_prepared_recovery_descriptor,
    remove_prepared_recovery_descriptor,
)
from sase.agent.hijack.recover_target import resolve_effective_target
from sase.agent.hijack.recovery_successor import RecoveryInheritanceError


@dataclass(frozen=True)
class PreparedRecovery:
    """All values reserved while the hijack record remains held."""

    subject: RecoverySubject
    record: dict[str, Any]
    hijack_id: str
    revision: int
    target: RecoveryTarget
    reserved_name: str
    resolver_pid: int | None
    resolver_token: str | None
    launch_identity: str
    request_id: str
    binding: dict[str, Any]
    descriptor: dict[str, Any]


def prepare_held_recovery(
    subject: RecoverySubject,
    record: dict[str, Any],
    hijack_id: str,
    revision: int,
    *,
    action: str,
    model: str | None,
    prompt: str | None,
    expected_revision: int | None,
    seams: RecoveryDeps,
) -> PreparedRecovery:
    """Validate and durably prepare one recovery before its state transition."""
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
    validate_pinned_target(record, target, mode="prepare", seams=seams)
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
    return PreparedRecovery(
        subject=subject,
        record=record,
        hijack_id=hijack_id,
        revision=revision,
        target=target,
        reserved_name=reserved_name,
        resolver_pid=resolver_pid,
        resolver_token=resolver_token,
        launch_identity=launch_identity,
        request_id=request_id,
        binding=binding,
        descriptor=descriptor,
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


def validate_pinned_target(
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

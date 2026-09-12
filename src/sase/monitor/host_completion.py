"""Host completion receiver for prepared no-model monitor success."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
)
from sase.core.continuation_facade import (
    consume_conditional_completion,
    evaluate_conditional_completion,
    invalidate_conditional_completion,
    resolve_continuation_policy,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.finalizer_wire import FinalizerPlanWire
from sase.finalizers.commit_repair import load_commit_results
from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import (
    authenticate_resolved_finalizer_plan,
    resolve_and_persist_finalizer_plan,
)
from sase.finalizers.prepare import (
    load_prepared_completion,
    observe_completion_repositories,
    persist_prepared_completion,
)
from sase.finalizers.providers import BUILTIN_PROVIDER_REFS
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import (
    delivery_key,
    load_delivery_record,
    load_host_completion_receipt,
    new_delivery_record,
    persist_delivery_record,
    persist_host_completion_receipt,
    transition_delivery,
)
from sase.monitor.diagnostics import diagnostic_manifest
from sase.shells.followup import FollowupLaunchResult
from sase.xprompt.directives import PromptDirectives

DEFAULT_RECOVERY_ACTION = (
    "Diagnose failures or stale verification, then finish the requested change."
)
HOST_COMPLETION_IDENTITY = "host-completion"
HOST_COMPLETED_OUTCOME = "host-completed"
FINALIZING_STATUS = "finalizing"
COMPLETED_BY_HOST_STATUS = "completed_by_host"
RECOVERY_STATUS = "recovery"
NEEDS_ATTENTION_STATUS = "needs_attention"


@dataclass(frozen=True, slots=True)
class _HostCompletionSettlement:
    """Settlement produced by attempting no-model host completion."""

    error: str | None = None
    launch_result: FollowupLaunchResult | None = None


class _NoModelProvider:
    """Provider adapter that refuses to start a model turn."""

    def invoke(self, *args: object, **kwargs: object) -> InvokeResult:
        raise RuntimeError("no-model host completion must not invoke a provider")


def settle_host_completion(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    project_name: str | None,
    launch_recovery: Callable[..., FollowupLaunchResult],
    release_claim: Callable[[dict[str, Any], str | None], str | None],
) -> _HostCompletionSettlement | None:
    """Attempt host completion when a prepared intent is bound.

    Returns ``None`` when the resolved policy is not ``complete`` so the
    caller can fall through to ordinary follow-up launch.
    """

    completion_ref = str(meta.get("monitor_completion_ref") or "")
    if not completion_ref:
        return None
    policy = resolve_continuation_policy(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "outcome": _policy_outcome(monitor_state),
            "profile": meta.get("monitor_profile") or None,
            "shared_next": meta.get("monitor_next_action") or None,
            "prepared_completion_ref": completion_ref,
        }
    )
    if policy.get("action") != "complete":
        return None
    if not str(meta.get("monitor_next_action") or "").strip():
        meta["monitor_next_action"] = DEFAULT_RECOVERY_ACTION
        update_meta_field(artifacts_dir, "monitor_next_action", DEFAULT_RECOVERY_ACTION)
    return _run_host_completion(
        artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        project_name=project_name,
        completion_ref=completion_ref,
        launch_recovery=launch_recovery,
        release_claim=release_claim,
    )


def _run_host_completion(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    project_name: str | None,
    completion_ref: str,
    launch_recovery: Callable[..., FollowupLaunchResult],
    release_claim: Callable[[dict[str, Any], str | None], str | None],
) -> _HostCompletionSettlement:
    receipt = load_host_completion_receipt(artifacts_dir)
    if receipt is not None and receipt.get("status") == "completed":
        _record_status(artifacts_dir, meta, COMPLETED_BY_HOST_STATUS)
        release_error = release_claim(meta, project_name)
        return _HostCompletionSettlement(
            error=release_error,
            launch_result=FollowupLaunchResult(
                launched=False,
                host_completed=True,
                agent_name=HOST_COMPLETION_IDENTITY,
            ),
        )
    if _ambiguous_commit(receipt, artifacts_dir):
        reason = "ambiguous_commit_receipt"
        _record_status(artifacts_dir, meta, NEEDS_ATTENTION_STATUS, reason=reason)
        persist_host_completion_receipt(
            artifacts_dir,
            {**(receipt or {}), "status": NEEDS_ATTENTION_STATUS, "reason": reason},
        )
        release_error = release_claim(meta, project_name)
        return _HostCompletionSettlement(
            error=release_error or reason,
            launch_result=FollowupLaunchResult(launched=False, error=reason),
        )

    _record_status(artifacts_dir, meta, FINALIZING_STATUS)
    persist_host_completion_receipt(
        artifacts_dir,
        {
            "schema_version": 1,
            "status": FINALIZING_STATUS,
            "intent_ref": completion_ref,
        },
    )
    key = delivery_key(
        monitor_id=str(meta.get("monitor_id") or "monitor"),
        result_id=str(meta.get("continuation_monitor_result_id") or "result"),
        branch="complete",
    )
    record = load_delivery_record(artifacts_dir, key) or new_delivery_record(
        key, selected_action="complete", reserved_identity=HOST_COMPLETION_IDENTITY
    )
    record = persist_delivery_record(
        artifacts_dir,
        transition_delivery(
            record,
            "acknowledged",
            acknowledged_by=HOST_COMPLETION_IDENTITY,
            reserved_identity=HOST_COMPLETION_IDENTITY,
        ),
    )

    intent_root = _intent_artifacts_dir(artifacts_dir, meta, project_name)
    try:
        intent = load_prepared_completion(completion_ref, artifacts_dir=intent_root)
        plan = _ensure_finalizer_plan(artifacts_dir)
        observations = observe_completion_repositories(Path(artifacts_dir))
        publication = publish_final_context(artifacts_dir=artifacts_dir)
        obligation_ids = [
            item.obligation_id
            for item in publication.context.obligations
            if item.kind == "repository"
        ]
        stages = list((diagnostic_manifest(artifacts_dir) or {}).get("stages") or [])
        decision = evaluate_conditional_completion(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent": intent,
                "outcome": _policy_outcome(monitor_state),
                "exit_code": exit_code,
                "command": _command_argv(meta),
                "observations": observations,
                "stages": stages,
                "executors": _executor_capabilities(plan),
                "workspace_identity": _workspace_identity(meta),
                "original_workspace_identity": _original_workspace_identity(
                    intent, meta
                ),
                "degraded_workspace": bool(
                    meta.get("monitor_followup_degraded_reason")
                ),
                "current_plan_digest": plan.plan_digest,
                "current_obligation_ids": obligation_ids,
                "substitutions": {
                    "duration": _format_duration(elapsed_seconds),
                    "evidence_ref": str(
                        meta.get("monitor_diagnostic_manifest_ref") or ""
                    ),
                },
            }
        )
    except (
        FinalizerDeclarationError,
        FinalizerControllerError,
        ValueError,
        OSError,
    ) as exc:
        return _recover(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            reason=str(exc),
            launch_recovery=launch_recovery,
            release_claim=release_claim,
            project_name=project_name,
            record=record,
        )

    if not decision.get("eligible"):
        reason = str(decision.get("reason") or "ineligible_completion")
        return _recover(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            reason=reason,
            launch_recovery=launch_recovery,
            release_claim=release_claim,
            project_name=project_name,
            record=record,
        )

    if receipt is not None and _commit_succeeded(artifacts_dir):
        return _finish_successful_completion(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            intent=intent,
            message=str(decision.get("rendered_message") or intent["success_message"]),
            record=record,
            release_claim=release_claim,
            project_name=project_name,
            rerun_finalizers=False,
        )

    try:
        _install_prepared_declaration(intent, artifacts_dir, publication)
        run_finalizers(
            provider=_NoModelProvider(),
            original_prompt=str(intent.get("success_message") or ""),
            invoke_result=InvokeResult(content=""),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=artifacts_dir,
            mode="no_model",
        )
    except Exception as exc:
        if _commit_succeeded(artifacts_dir):
            persist_host_completion_receipt(
                artifacts_dir,
                {
                    "schema_version": 1,
                    "status": NEEDS_ATTENTION_STATUS,
                    "reason": f"commit_succeeded_but_completion_failed:{exc}",
                    "intent_ref": completion_ref,
                },
            )
            _record_status(
                artifacts_dir,
                meta,
                NEEDS_ATTENTION_STATUS,
                reason=str(exc),
            )
            release_error = release_claim(meta, project_name)
            return _HostCompletionSettlement(
                error=release_error or str(exc),
                launch_result=FollowupLaunchResult(launched=False, error=str(exc)),
            )
        return _recover(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            reason=str(exc),
            launch_recovery=launch_recovery,
            release_claim=release_claim,
            project_name=project_name,
            record=record,
        )

    return _finish_successful_completion(
        artifacts_dir,
        meta,
        intent_root=intent_root,
        completion_ref=completion_ref,
        intent=intent,
        message=str(decision.get("rendered_message") or intent["success_message"]),
        record=record,
        release_claim=release_claim,
        project_name=project_name,
        rerun_finalizers=False,
    )


def _finish_successful_completion(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    intent_root: str,
    completion_ref: str,
    intent: Mapping[str, Any],
    message: str,
    record: Mapping[str, Any],
    release_claim: Callable[[dict[str, Any], str | None], str | None],
    project_name: str | None,
    rerun_finalizers: bool,
) -> _HostCompletionSettlement:
    del rerun_finalizers
    consumed = consume_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": dict(intent),
        }
    )
    persist_prepared_completion(consumed, artifacts_dir=intent_root)
    persist_delivery_record(
        artifacts_dir,
        transition_delivery(
            record, "settled", acknowledged_by=HOST_COMPLETION_IDENTITY
        ),
    )
    persist_host_completion_receipt(
        artifacts_dir,
        {
            "schema_version": 1,
            "status": "completed",
            "intent_id": consumed.get("intent_id"),
            "intent_ref": completion_ref,
            "published_message": message,
            "commit_receipts": load_commit_results(artifact_root(artifacts_dir)),
        },
    )
    meta["monitor_host_completion_message"] = message
    update_meta_field(artifacts_dir, "monitor_host_completion_message", message)
    meta["monitor_followup_outcome"] = HOST_COMPLETED_OUTCOME
    update_meta_field(artifacts_dir, "monitor_followup_outcome", HOST_COMPLETED_OUTCOME)
    _record_status(artifacts_dir, meta, COMPLETED_BY_HOST_STATUS)
    release_error = release_claim(meta, project_name)
    return _HostCompletionSettlement(
        error=release_error,
        launch_result=FollowupLaunchResult(
            launched=False,
            host_completed=True,
            agent_name=HOST_COMPLETION_IDENTITY,
        ),
    )


def _recover(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    intent_root: str,
    completion_ref: str,
    reason: str,
    launch_recovery: Callable[..., FollowupLaunchResult],
    release_claim: Callable[[dict[str, Any], str | None], str | None],
    project_name: str | None,
    record: Mapping[str, Any],
) -> _HostCompletionSettlement:
    try:
        intent = load_prepared_completion(completion_ref, artifacts_dir=intent_root)
        invalidated = invalidate_conditional_completion(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent": intent,
            }
        )
        persist_prepared_completion(invalidated, artifacts_dir=intent_root)
    except (FinalizerDeclarationError, ValueError, OSError):
        pass
    persist_delivery_record(
        artifacts_dir,
        transition_delivery(
            record,
            "needs_attention",
            reason=reason,
            acknowledged_by=HOST_COMPLETION_IDENTITY,
        ),
    )
    persist_host_completion_receipt(
        artifacts_dir,
        {
            "schema_version": 1,
            "status": RECOVERY_STATUS,
            "reason": reason,
            "intent_ref": completion_ref,
        },
    )
    _record_status(artifacts_dir, meta, RECOVERY_STATUS, reason=reason)
    launch_result = launch_recovery(artifacts_dir, meta)
    if not launch_result.launched:
        release_error = release_claim(meta, project_name)
        return _HostCompletionSettlement(
            error=release_error or launch_result.error or reason,
            launch_result=launch_result,
        )
    return _HostCompletionSettlement(launch_result=launch_result)


def _install_prepared_declaration(
    intent: Mapping[str, Any],
    artifacts_dir: str,
    publication: Any,
) -> None:
    declaration = deepcopy(intent.get("declaration") or {})
    if not isinstance(declaration, dict):
        raise FinalizerDeclarationError(
            "prepared declaration is not an object",
            code="malformed_completion_intent",
        )
    if publication.context.context_digest:
        declaration["context_digest"] = publication.context.context_digest
    plan = authenticate_resolved_finalizer_plan(artifacts_dir)
    declaration["plan_digest"] = plan.plan_digest
    os.environ.setdefault("SASE_AGENT_TIMESTAMP", Path(artifacts_dir).name)
    os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
    submit_final_manifest(declaration, artifacts_dir=artifacts_dir)


def _ensure_finalizer_plan(artifacts_dir: str) -> FinalizerPlanWire:
    try:
        return authenticate_resolved_finalizer_plan(artifacts_dir)
    except Exception:
        resolved = resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=artifacts_dir
        )
        if resolved is None:
            raise FinalizerControllerError(
                "no-model host completion could not resolve a finalizer plan",
                code="no_model_missing_plan",
            ) from None
        return resolved.plan


def _executor_capabilities(plan: FinalizerPlanWire) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for entry in plan.entries:
        builtin = entry.provider_ref in BUILTIN_PROVIDER_REFS
        capabilities.append(
            {
                "instance_id": entry.instance_id,
                "provider_ref": entry.provider_ref,
                "headless": builtin,
                "durable_replay": builtin,
                "requires_model": not builtin,
            }
        )
    return capabilities


def _intent_artifacts_dir(
    artifacts_dir: str,
    meta: Mapping[str, Any],
    project_name: str | None,
) -> str:
    parent = meta.get("parent_timestamp")
    if project_name and isinstance(parent, str) and parent:
        starter = canonical_agent_artifact_path(
            project_name, ACE_RUN_WORKFLOW_DIR, parent
        )
        if starter.is_dir():
            return str(starter)
    return artifacts_dir


def _command_argv(meta: Mapping[str, Any]) -> list[str]:
    raw = meta.get("monitor_execution_argv")
    if isinstance(raw, Sequence) and not isinstance(raw, str | bytes) and raw:
        return [str(part) for part in raw]
    command = str(meta.get("monitor_command") or "")
    return command.split() if command else []


def _workspace_identity(meta: Mapping[str, Any]) -> str:
    return str(
        meta.get("continuation_workspace_ref")
        or meta.get("workspace_dir")
        or meta.get("workspace_num")
        or "unknown"
    )


def _original_workspace_identity(
    intent: Mapping[str, Any],
    meta: Mapping[str, Any],
) -> str:
    creator = (intent.get("seal") or {}).get("creator") or {}
    workspace_id = creator.get("workspace_id")
    if workspace_id:
        current = str(meta.get("workspace_num") or "")
        if current and current == str(workspace_id):
            return _workspace_identity(meta)
        return str(workspace_id)
    return _workspace_identity(meta)


def _policy_outcome(monitor_state: str) -> str:
    if monitor_state in {"completed", "failed", "timeout", "stopped", "lost"}:
        return monitor_state
    return "unknown"


def _format_duration(elapsed_seconds: float) -> str:
    total = max(0, int(round(elapsed_seconds)))
    minutes, seconds = divmod(total, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _record_status(
    artifacts_dir: str,
    meta: dict[str, Any],
    status: str,
    *,
    reason: str | None = None,
) -> None:
    meta["monitor_host_completion_status"] = status
    update_meta_field(artifacts_dir, "monitor_host_completion_status", status)
    if reason:
        meta["monitor_host_completion_reason"] = reason
        update_meta_field(artifacts_dir, "monitor_host_completion_reason", reason)


def _commit_succeeded(artifacts_dir: str) -> bool:
    markers = load_commit_results(artifact_root(artifacts_dir))
    return any(
        isinstance(marker, Mapping) and marker.get("result") == "ok"
        for marker in markers
    )


def _ambiguous_commit(receipt: Mapping[str, Any] | None, artifacts_dir: str) -> bool:
    if receipt is None:
        return False
    if receipt.get("status") != FINALIZING_STATUS:
        return False
    if receipt.get("ambiguous"):
        return True
    markers = load_commit_results(artifact_root(artifacts_dir))
    return any(
        isinstance(marker, Mapping)
        and marker.get("result") not in {None, "ok"}
        and "sha" not in marker
        for marker in markers
    )


__all__ = [
    "DEFAULT_RECOVERY_ACTION",
    "COMPLETED_BY_HOST_STATUS",
    "FINALIZING_STATUS",
    "HOST_COMPLETED_OUTCOME",
    "HOST_COMPLETION_IDENTITY",
    "NEEDS_ATTENTION_STATUS",
    "RECOVERY_STATUS",
    "settle_host_completion",
]

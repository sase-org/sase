"""Host completion receiver for prepared no-model monitor success."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.continuation_facade import (
    consume_conditional_completion,
    invalidate_conditional_completion,
    resolve_continuation_policy,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.commit_repair import load_commit_results
from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    mint_finalizer_turn_nonce,
)
from sase.finalizers.prepare import (
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import (
    adopt_host_completion_delivery,
    delivery_key,
    load_host_completion_receipt,
    new_delivery_record,
    persist_delivery_record,
    persist_host_completion_receipt,
    transition_delivery,
)
from sase.monitor.host_completion_state import (
    FINALIZING_STATUS,
    RECOVERY_STATUS,
    all_required_actions_complete,
    ambiguous_commit,
    can_finish_without_rerun,
    ensure_finalizer_plan,
    evaluate_intent,
    execution_context_drifted,
    executor_capabilities,
    install_prepared_declaration,
    intent_artifacts_dir,
    new_obligation_ids,
    record_status,
    recovery_launch_kwargs,
    required_commit_repo_ids,
    should_resume_outstanding,
    snapshot_execution_context,
    workspace_identity,
)
from sase.monitor.output import OutputCapture
from sase.shells.followup import FollowupLaunchResult

DEFAULT_RECOVERY_ACTION = (
    "Diagnose failures or stale verification, then finish the requested change."
)
HOST_COMPLETION_IDENTITY = "host-completion"
HOST_COMPLETED_OUTCOME = "host-completed"
COMPLETED_BY_HOST_STATUS = "completed_by_host"
NEEDS_ATTENTION_STATUS = "needs_attention"

# Test seams: unit tests patch these names on this module.
_ensure_finalizer_plan = ensure_finalizer_plan
_evaluate_intent = evaluate_intent
_executor_capabilities = executor_capabilities
_install_prepared_declaration = install_prepared_declaration
_snapshot_execution_context = snapshot_execution_context


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
    capture: OutputCapture,
    selected_action: str | None = None,
    timeout_kind: str | None = None,
    transfer_from_pid: int | None = None,
) -> _HostCompletionSettlement | None:
    """Attempt host completion when a prepared intent is bound.

    Returns ``None`` when the resolved policy is not ``complete`` so the
    caller can fall through to ordinary follow-up launch.
    """

    completion_ref = str(meta.get("monitor_completion_ref") or "") or str(
        meta.get("continuation_completion_ref") or ""
    )
    if not completion_ref:
        return None
    if selected_action != "complete":
        policy = resolve_continuation_policy(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "outcome": _policy_outcome_name(monitor_state),
                "profile": meta.get("monitor_profile") or None,
                "shared_next": meta.get("monitor_next_action") or None,
                "prepared_completion_ref": completion_ref,
            }
        )
        if policy.get("action") != "complete":
            return None
    if not str(meta.get("monitor_next_action") or "").strip():
        meta["monitor_next_action"] = DEFAULT_RECOVERY_ACTION
        from sase.axe.run_agent_helpers_artifacts import update_meta_field

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
        capture=capture,
        timeout_kind=timeout_kind,
        transfer_from_pid=transfer_from_pid,
    )


def _policy_outcome_name(monitor_state: str) -> str:
    from sase.monitor.host_completion_state import policy_outcome

    return policy_outcome(monitor_state)


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
    capture: OutputCapture,
    timeout_kind: str | None,
    transfer_from_pid: int | None,
) -> _HostCompletionSettlement:
    receipt = load_host_completion_receipt(artifacts_dir)
    if receipt is not None and receipt.get("status") == "completed":
        record_status(artifacts_dir, meta, COMPLETED_BY_HOST_STATUS)
        release_error = release_claim(meta, project_name)
        return _HostCompletionSettlement(
            error=release_error,
            launch_result=FollowupLaunchResult(
                launched=False,
                host_completed=True,
                agent_name=HOST_COMPLETION_IDENTITY,
            ),
        )
    if ambiguous_commit(receipt, artifacts_dir):
        reason = "ambiguous_commit_receipt"
        record_status(artifacts_dir, meta, NEEDS_ATTENTION_STATUS, reason=reason)
        persist_host_completion_receipt(
            artifacts_dir,
            {**(receipt or {}), "status": NEEDS_ATTENTION_STATUS, "reason": reason},
        )
        release_error = release_claim(meta, project_name)
        return _HostCompletionSettlement(
            error=release_error or reason,
            launch_result=FollowupLaunchResult(launched=False, error=reason),
        )

    recover_kw = recovery_launch_kwargs(
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        capture=capture,
        project_name=project_name,
        timeout_kind=timeout_kind,
        transfer_from_pid=transfer_from_pid,
    )
    key = delivery_key(
        monitor_id=str(meta.get("monitor_id") or "monitor"),
        result_id=str(meta.get("continuation_monitor_result_id") or "result"),
        branch="complete",
    )
    record: Mapping[str, Any] = new_delivery_record(
        key,
        selected_action="complete",
        reserved_identity=HOST_COMPLETION_IDENTITY,
    )
    intent_root = intent_artifacts_dir(artifacts_dir, meta, project_name)
    if bool(meta.get("monitor_followup_degraded_reason")):
        return _recover(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            reason="degraded_workspace",
            launch_recovery=launch_recovery,
            release_claim=release_claim,
            project_name=project_name,
            record=record,
            **recover_kw,
        )

    record_status(artifacts_dir, meta, FINALIZING_STATUS)
    persist_host_completion_receipt(
        artifacts_dir,
        {
            "schema_version": 1,
            "status": FINALIZING_STATUS,
            "intent_ref": completion_ref,
            **(receipt or {}),
        },
    )

    try:
        record = adopt_host_completion_delivery(
            artifacts_dir,
            key,
            reserved_identity=HOST_COMPLETION_IDENTITY,
            workspace_identity=workspace_identity(meta),
            workspace_degraded=False,
        )
        if str(record.get("disposition") or "") in {
            "cancelled",
            "nonlaunchable",
            "needs_attention",
        }:
            reason = str(record.get("disposition_reason") or record["disposition"])
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
                **recover_kw,
            )
        intent = load_prepared_completion(completion_ref, artifacts_dir=intent_root)
        snapshot = _snapshot_execution_context(artifacts_dir, meta)
        resuming = should_resume_outstanding(
            receipt, intent, snapshot.plan, artifacts_dir
        )
        if not resuming:
            decision = _evaluate_intent(
                artifacts_dir,
                meta,
                intent=intent,
                snapshot=snapshot,
                monitor_state=monitor_state,
                exit_code=exit_code,
                elapsed_seconds=elapsed_seconds,
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
                    **recover_kw,
                )
            rendered = str(
                decision.get("rendered_message") or intent["success_message"]
            )
        else:
            rendered = str(intent.get("success_message") or "")
            decision = {"rendered_message": rendered}
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
            **recover_kw,
        )

    persist_host_completion_receipt(
        artifacts_dir,
        {
            "schema_version": 1,
            "status": FINALIZING_STATUS,
            "intent_ref": completion_ref,
            "required_repo_ids": required_commit_repo_ids(intent),
            "required_instance_ids": [
                entry.instance_id for entry in snapshot.plan.entries
            ],
        },
    )

    if can_finish_without_rerun(intent, snapshot.plan, artifacts_dir) and not (
        new_obligation_ids(intent, snapshot.obligation_ids)
    ):
        return _finish_successful_completion(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            intent=intent,
            message=rendered,
            record=record,
            release_claim=release_claim,
            project_name=project_name,
        )

    try:
        mint_finalizer_turn_nonce()
        pre_exec = _snapshot_execution_context(artifacts_dir, meta)
        if not resuming and execution_context_drifted(snapshot, pre_exec):
            return _recover(
                artifacts_dir,
                meta,
                intent_root=intent_root,
                completion_ref=completion_ref,
                reason="tree_drift_before_execution",
                launch_recovery=launch_recovery,
                release_claim=release_claim,
                project_name=project_name,
                record=record,
                **recover_kw,
            )
        new_ids = new_obligation_ids(intent, pre_exec.obligation_ids)
        if new_ids:
            return _recover(
                artifacts_dir,
                meta,
                intent_root=intent_root,
                completion_ref=completion_ref,
                reason="new_repository_obligation:" + ",".join(new_ids),
                launch_recovery=launch_recovery,
                release_claim=release_claim,
                project_name=project_name,
                record=record,
                **recover_kw,
            )
        _install_prepared_declaration(intent, artifacts_dir, pre_exec.publication)
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
        if ambiguous_commit(load_host_completion_receipt(artifacts_dir), artifacts_dir):
            reason = f"ambiguous_external_action:{exc}"
            persist_host_completion_receipt(
                artifacts_dir,
                {
                    "schema_version": 1,
                    "status": NEEDS_ATTENTION_STATUS,
                    "reason": reason,
                    "intent_ref": completion_ref,
                    "commit_receipts": load_commit_results(
                        artifact_root(artifacts_dir)
                    ),
                },
            )
            record_status(artifacts_dir, meta, NEEDS_ATTENTION_STATUS, reason=reason)
            release_error = release_claim(meta, project_name)
            return _HostCompletionSettlement(
                error=release_error or reason,
                launch_result=FollowupLaunchResult(launched=False, error=reason),
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
            **recover_kw,
        )

    try:
        post = _snapshot_execution_context(artifacts_dir, meta)
    except (FinalizerDeclarationError, FinalizerControllerError, ValueError, OSError):
        post = None
    if post is not None:
        new_ids = new_obligation_ids(intent, post.obligation_ids)
        if new_ids:
            return _recover(
                artifacts_dir,
                meta,
                intent_root=intent_root,
                completion_ref=completion_ref,
                reason="new_repository_obligation:" + ",".join(new_ids),
                launch_recovery=launch_recovery,
                release_claim=release_claim,
                project_name=project_name,
                record=record,
                **recover_kw,
            )
    if not all_required_actions_complete(intent, snapshot.plan, artifacts_dir):
        return _recover(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            reason="outstanding_finalizer_actions",
            launch_recovery=launch_recovery,
            release_claim=release_claim,
            project_name=project_name,
            record=record,
            **recover_kw,
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
) -> _HostCompletionSettlement:
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
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "monitor_host_completion_message", message)
    meta["monitor_followup_outcome"] = HOST_COMPLETED_OUTCOME
    update_meta_field(artifacts_dir, "monitor_followup_outcome", HOST_COMPLETED_OUTCOME)
    record_status(artifacts_dir, meta, COMPLETED_BY_HOST_STATUS)
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
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    timeout_kind: str | None = None,
    transfer_from_pid: int | None = None,
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
    if str(record.get("disposition") or "") not in {
        "cancelled",
        "nonlaunchable",
        "needs_attention",
        "settled",
    }:
        try:
            persist_delivery_record(
                artifacts_dir,
                transition_delivery(
                    record,
                    "needs_attention",
                    reason=reason,
                    acknowledged_by=HOST_COMPLETION_IDENTITY,
                ),
            )
        except (ValueError, OSError):
            pass
    persist_host_completion_receipt(
        artifacts_dir,
        {
            "schema_version": 1,
            "status": RECOVERY_STATUS,
            "reason": reason,
            "intent_ref": completion_ref,
            "commit_receipts": load_commit_results(artifact_root(artifacts_dir)),
        },
    )
    record_status(artifacts_dir, meta, RECOVERY_STATUS, reason=reason)
    launch_result = launch_recovery(
        artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        capture=capture,
        project_name=project_name or "",
        timeout_kind=timeout_kind,
        transfer_from_pid=transfer_from_pid,
    )
    if not launch_result.launched:
        release_error = release_claim(meta, project_name)
        return _HostCompletionSettlement(
            error=release_error or launch_result.error or reason,
            launch_result=launch_result,
        )
    return _HostCompletionSettlement(launch_result=launch_result)


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

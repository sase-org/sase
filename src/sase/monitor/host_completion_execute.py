"""No-model plan execution for host completion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.finalizers.commit_repair import load_commit_results
from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    mint_finalizer_turn_nonce,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.types import InvokeResult
from sase.monitor._host_completion_shared import (
    HOST_COMPLETION_IDENTITY,
    NEEDS_ATTENTION_STATUS,
    HostCompletionSettlement,
    verdict_receipt_record,
)
from sase.monitor.delivery import (
    load_host_completion_receipt,
    persist_host_completion_receipt,
)
from sase.monitor.host_completion_complete import (
    finish_successful_completion,
    recover_host_completion,
)
from sase.monitor.host_completion_state import (
    FINALIZING_STATUS,
    all_required_actions_complete,
    ambiguous_commit,
    can_finish_without_rerun,
    execution_context_drifted,
    install_prepared_declaration,
    new_obligation_ids,
    record_status,
    required_commit_repo_ids,
    snapshot_execution_context,
)
from sase.monitor.no_new_receipt import NoNewEvidence, verify_no_new_receipt
from sase.turns.followup import FollowupLaunchResult

# Test seams: unit tests patch these names on this module.
_install_prepared_declaration = install_prepared_declaration
_snapshot_execution_context = snapshot_execution_context
_verify_no_new_receipt = verify_no_new_receipt


class _NoModelProvider:
    """Provider adapter that refuses to start a model turn."""

    def invoke(self, *args: object, **kwargs: object) -> InvokeResult:
        raise RuntimeError("no-model host completion must not invoke a provider")


def execute_host_completion(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    intent: Mapping[str, Any],
    snapshot: Any,
    decision: dict[str, Any],
    rendered: str,
    evidence: NoNewEvidence | None,
    resuming: bool,
    no_new: bool,
    intent_root: str,
    completion_ref: str,
    record: Mapping[str, Any],
    launch_recovery: Callable[..., FollowupLaunchResult],
    release_claim: Callable[[dict[str, Any], str | None], str | None],
    project_name: str | None,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    recover_kw: dict[str, Any],
) -> HostCompletionSettlement:
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
            **verdict_receipt_record(evidence),
        },
    )

    if can_finish_without_rerun(intent, snapshot.plan, artifacts_dir) and not (
        new_obligation_ids(intent, snapshot.obligation_ids)
    ):
        if no_new:
            # The shortcut must never bypass the precommit gate: re-observe
            # every obligated repository and repeat the receipt lookup for
            # the same receipt and source run before finishing.
            gate, gate_reason = _verify_no_new_receipt(
                intent=intent,
                meta=meta,
                monitor_state=monitor_state,
                expected_receipt_id=evidence.receipt_id if evidence else None,
                expected_run_id=evidence.run_id if evidence else None,
            )
            if gate is None or gate_reason is not None:
                return recover_host_completion(
                    artifacts_dir,
                    meta,
                    intent_root=intent_root,
                    completion_ref=completion_ref,
                    reason=str(gate_reason or "no_new_receipt_refused"),
                    launch_recovery=launch_recovery,
                    release_claim=release_claim,
                    project_name=project_name,
                    record=record,
                    **recover_kw,
                )
            evidence = gate
        return finish_successful_completion(
            artifacts_dir,
            meta,
            intent_root=intent_root,
            completion_ref=completion_ref,
            intent=intent,
            message=rendered,
            record=record,
            release_claim=release_claim,
            project_name=project_name,
            evidence=evidence,
        )

    try:
        mint_finalizer_turn_nonce()
        pre_exec = _snapshot_execution_context(artifacts_dir, meta)
        if not resuming and execution_context_drifted(snapshot, pre_exec):
            return recover_host_completion(
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
            return recover_host_completion(
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
        if no_new:
            # Host-owned precommit gate: re-observe all obligated
            # repositories immediately before the first mutating commit
            # action and repeat the Rust lookup for the same receipt and
            # source run. Refuse the whole completion before any commit
            # when the tree drifted or the receipt no longer covers it.
            gate, gate_reason = _verify_no_new_receipt(
                intent=intent,
                meta=meta,
                monitor_state=monitor_state,
                expected_receipt_id=evidence.receipt_id if evidence else None,
                expected_run_id=evidence.run_id if evidence else None,
            )
            if gate is None or gate_reason is not None:
                return recover_host_completion(
                    artifacts_dir,
                    meta,
                    intent_root=intent_root,
                    completion_ref=completion_ref,
                    reason=str(gate_reason or "no_new_receipt_refused"),
                    launch_recovery=launch_recovery,
                    release_claim=release_claim,
                    project_name=project_name,
                    record=record,
                    **recover_kw,
                )
            evidence = gate
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
            return HostCompletionSettlement(
                error=release_error or reason,
                launch_result=FollowupLaunchResult(launched=False, error=reason),
            )
        return recover_host_completion(
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
            return recover_host_completion(
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
        return recover_host_completion(
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

    return finish_successful_completion(
        artifacts_dir,
        meta,
        intent_root=intent_root,
        completion_ref=completion_ref,
        intent=intent,
        message=str(decision.get("rendered_message") or intent["success_message"]),
        record=record,
        release_claim=release_claim,
        project_name=project_name,
        evidence=evidence,
    )


__all__ = [
    "execute_host_completion",
]

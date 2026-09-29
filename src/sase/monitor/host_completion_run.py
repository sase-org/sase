"""Core no-model host-completion orchestration (admission and eligibility)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.finalizers.controller import FinalizerControllerError
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.finalizers.prepare import load_prepared_completion
from sase.monitor._host_completion_shared import (
    COMPLETED_BY_HOST_STATUS,
    HOST_COMPLETION_IDENTITY,
    NEEDS_ATTENTION_STATUS,
    HostCompletionSettlement,
)
from sase.monitor.delivery import (
    adopt_host_completion_delivery,
    delivery_key,
    load_host_completion_receipt,
    new_delivery_record,
    persist_host_completion_receipt,
)
from sase.monitor.host_completion_complete import recover_host_completion
from sase.monitor.host_completion_execute import execute_host_completion
from sase.monitor.host_completion_state import (
    FINALIZING_STATUS,
    ambiguous_commit,
    ensure_finalizer_plan,
    evaluate_intent,
    executor_capabilities,
    intent_artifacts_dir,
    record_status,
    recovery_launch_kwargs,
    should_resume_outstanding,
    snapshot_execution_context,
    workspace_identity,
)
from sase.monitor.no_new_receipt import (
    NoNewEvidence,
    is_no_new_intent,
    verify_no_new_receipt,
)
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult

# Test seams: unit tests patch these names on this module.
_ensure_finalizer_plan = ensure_finalizer_plan
_evaluate_intent = evaluate_intent
_executor_capabilities = executor_capabilities
_snapshot_execution_context = snapshot_execution_context
_verify_no_new_receipt = verify_no_new_receipt


def run_host_completion(
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
) -> HostCompletionSettlement:
    receipt = load_host_completion_receipt(artifacts_dir)
    if receipt is not None and receipt.get("status") == "completed":
        record_status(artifacts_dir, meta, COMPLETED_BY_HOST_STATUS)
        release_error = release_claim(meta, project_name)
        return HostCompletionSettlement(
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
        return HostCompletionSettlement(
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
        return recover_host_completion(
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
            return recover_host_completion(
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
        no_new = is_no_new_intent(intent)
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
                return recover_host_completion(
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
        evidence: NoNewEvidence | None = None
        if no_new:
            # At monitor settlement, retrieve the settled ToolRun from the
            # monitor/owner link and require a covering no_new_failures
            # receipt from that exact run. Resumed host completion re-runs
            # the same gate instead of trusting a persisted prior success.
            expected = _expected_no_new_ids(receipt if resuming else None)
            if resuming:
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
                    return recover_host_completion(
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
            evidence, no_new_reason = _verify_no_new_receipt(
                intent=intent,
                meta=meta,
                monitor_state=monitor_state,
                expected_receipt_id=expected[0],
                expected_run_id=expected[1],
            )
            if evidence is None or no_new_reason is not None:
                return recover_host_completion(
                    artifacts_dir,
                    meta,
                    intent_root=intent_root,
                    completion_ref=completion_ref,
                    reason=str(no_new_reason or "no_new_receipt_refused"),
                    launch_recovery=launch_recovery,
                    release_claim=release_claim,
                    project_name=project_name,
                    record=record,
                    **recover_kw,
                )
    except (
        FinalizerDeclarationError,
        FinalizerControllerError,
        ValueError,
        OSError,
    ) as exc:
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

    return execute_host_completion(
        artifacts_dir,
        meta,
        intent=intent,
        snapshot=snapshot,
        decision=decision,
        rendered=rendered,
        evidence=evidence,
        resuming=resuming,
        no_new=no_new,
        intent_root=intent_root,
        completion_ref=completion_ref,
        record=record,
        launch_recovery=launch_recovery,
        release_claim=release_claim,
        project_name=project_name,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        recover_kw=recover_kw,
    )


def _expected_no_new_ids(
    receipt: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Return the persisted verdict receipt/run ids a resumed gate must repeat.

    Resumed host completion re-runs the receipt lookup instead of trusting a
    persisted prior success; pinning the same receipt and source run closes
    the TOCTOU window between settlement and the precommit gate.
    """

    if not isinstance(receipt, Mapping):
        return None, None
    verdict = receipt.get("verdict_receipt")
    if not isinstance(verdict, Mapping):
        return None, None
    receipt_id = verdict.get("receipt_id")
    run_id = verdict.get("run_id")
    return (
        str(receipt_id) if isinstance(receipt_id, str) and receipt_id else None,
        str(run_id) if isinstance(run_id, str) and run_id else None,
    )


__all__ = [
    "run_host_completion",
]

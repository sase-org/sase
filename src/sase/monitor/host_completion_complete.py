"""Successful-finish and recovery paths for host completion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.core.continuation_facade import (
    consume_conditional_completion,
    invalidate_conditional_completion,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.commit_repair import load_commit_results
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.finalizers.prepare import (
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.monitor._host_completion_shared import (
    COMPLETED_BY_HOST_STATUS,
    HOST_COMPLETED_OUTCOME,
    HOST_COMPLETION_IDENTITY,
    HostCompletionSettlement,
    verdict_receipt_record,
)
from sase.monitor.delivery import (
    persist_delivery_record,
    persist_host_completion_receipt,
    transition_delivery,
)
from sase.monitor.host_completion_state import RECOVERY_STATUS, record_status
from sase.monitor.no_new_receipt import NoNewEvidence
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult


def finish_successful_completion(
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
    evidence: NoNewEvidence | None = None,
) -> HostCompletionSettlement:
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
            **verdict_receipt_record(evidence),
        },
    )
    meta["monitor_host_completion_message"] = message
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "monitor_host_completion_message", message)
    meta["monitor_followup_outcome"] = HOST_COMPLETED_OUTCOME
    update_meta_field(artifacts_dir, "monitor_followup_outcome", HOST_COMPLETED_OUTCOME)
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


def recover_host_completion(
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
) -> HostCompletionSettlement:
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
        return HostCompletionSettlement(
            error=release_error or launch_result.error or reason,
            launch_result=launch_result,
        )
    return HostCompletionSettlement(launch_result=launch_result)


__all__ = [
    "finish_successful_completion",
    "recover_host_completion",
]

"""Retention for a gate publication that failed after its creator ended."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.gate_turn._transaction_creator import CreatorContext
from sase.gate_turn.log import append_gate_turn_log_text
from sase.gate_turn.models import GateTurnRecord


def retain_failed_gate_origin(
    creator: CreatorContext,
    record: GateTurnRecord,
    *,
    reason: str,
) -> None:
    """Settle dirty work for the exact creator claim after detached failure.

    The gate member may have been created by a later session member than the
    RUNNING claim's artifact timestamp. Resolve the expected claim using the
    persisted root identity and require one exact row before applying any
    effect. Repository evidence still comes from the member that staged the
    gate, while the retention record and pending marker live beside the
    actual claim owner so stale cleanup can find them.
    """
    workspace_num = creator.workspace_num
    pid = creator.runner_pid
    artifacts_timestamp = creator.claim_artifacts_timestamp or creator.timestamp
    if workspace_num is None or workspace_num <= 0 or pid is None:
        _log(record, "origin claim identity is incomplete; claim was left untouched")
        return

    from sase.running_field import get_claimed_workspaces

    try:
        claims = get_claimed_workspaces(creator.project_file)
    except Exception as exc:  # noqa: BLE001 - identity uncertainty cannot mutate.
        _log(
            record, f"could not inspect creator claim; claim was left untouched: {exc}"
        )
        return
    matches = [
        claim
        for claim in claims
        if claim.workspace_num == workspace_num
        and claim.pid == pid
        and (claim.cl_name or "") == (creator.cl_name or "")
        and (claim.artifacts_timestamp or "") == artifacts_timestamp
    ]
    if len(matches) != 1:
        _log(
            record,
            "creator claim identity changed or is ambiguous; no claim effect was applied",
        )
        return
    claim = matches[0]
    if not claim.workflow or not (claim.artifacts_timestamp or ""):
        _log(
            record,
            "creator claim identity is incomplete; claim was left untouched",
        )
        return
    claim_artifacts_dir = creator.claim_artifacts_dir or str(
        Path(creator.artifacts_dir).parent / artifacts_timestamp
    )
    checkout_dir = creator.meta.get("workspace_dir")
    if not isinstance(checkout_dir, str) or not checkout_dir.strip():
        checkout_dir = None

    try:
        from sase.turns.workspace_retention import (
            WorkspaceRetentionOwner,
            discover_workspace_retention_repos,
        )

        repos, origin_repo_ids = discover_workspace_retention_repos(
            creator.artifacts_dir,
            checkout_dir,
        )
        owner = WorkspaceRetentionOwner(
            project_file=creator.project_file,
            workspace_num=claim.workspace_num,
            workflow=claim.workflow,
            cl_name=claim.cl_name or "",
            artifacts_timestamp=claim.artifacts_timestamp or "",
            pid=claim.pid,
            artifacts_dir=claim_artifacts_dir,
            checkout_dir=checkout_dir,
            repos=repos,
            origin_repo_ids=origin_repo_ids,
            session_id=creator.durable_lane,
            turn_id=record.gate_id,
            terminal_reason=reason,
            evidence_artifacts_dir=creator.artifacts_dir,
            notify_on_retain=True,
        )
        from sase.turns.workspace_retention import (
            clear_pending_retention,
            settle_stranded_workspace,
            write_pending_retention,
        )

        pending_path = write_pending_retention(owner, "failed_gate_publication")
        if pending_path is None:
            _pin_exact_claim(owner)
        result = settle_stranded_workspace(owner)
        clear_pending_retention(owner.artifacts_dir)
    except Exception as exc:  # noqa: BLE001 - failed policy must keep custody.
        if "owner" in locals():
            _pin_exact_claim(owner)
            try:
                from sase.turns.workspace_retention import write_pending_retention

                write_pending_retention(owner, f"gate_settlement_failed: {exc}")
            except Exception:  # noqa: BLE001 - the guarded pin remains primary.
                pass
        elif "claim" in locals():
            _pin_claim(
                creator.project_file,
                workspace_num=claim.workspace_num,
                workflow=claim.workflow,
                cl_name=claim.cl_name or "",
                artifacts_timestamp=claim.artifacts_timestamp or "",
                pid=claim.pid,
            )
        _log(record, f"workspace retention decision failed: {exc}")
        return

    try:
        from sase.axe.run_agent_helpers_artifacts import update_meta_fields

        update_meta_fields(
            record.artifacts_dir,
            {
                "workspace_retention_origin_artifacts_dir": owner.artifacts_dir,
                "workspace_retention_origin_record_path": result.record_path,
                "workspace_retention_origin_disposition": result.disposition,
                "workspace_retention_origin_reason": result.reason,
            },
        )
    except Exception:  # noqa: BLE001 - the durable source record is authoritative.
        pass
    _log(record, f"origin workspace retention: {result.disposition} ({result.reason})")


def _pin_exact_claim(owner: Any) -> None:
    _pin_claim(
        owner.project_file,
        workspace_num=owner.workspace_num,
        workflow=owner.workflow,
        cl_name=owner.cl_name,
        artifacts_timestamp=owner.artifacts_timestamp,
        pid=owner.pid,
    )


def _pin_claim(
    project_file: str,
    *,
    workspace_num: int,
    workflow: str,
    cl_name: str,
    artifacts_timestamp: str,
    pid: int,
) -> None:
    from sase.running_field import hold_workspace_claim

    hold_workspace_claim(
        project_file,
        workspace_num,
        workflow,
        cl_name,
        artifacts_timestamp,
        caller_tag="failed-gate-retention-failure",
        expected_pid=pid,
    )


def _log(record: GateTurnRecord, message: str) -> None:
    append_gate_turn_log_text(
        record.artifacts_dir,
        f"! gate-origin-retention: {message}\n",
    )


__all__ = ["retain_failed_gate_origin"]

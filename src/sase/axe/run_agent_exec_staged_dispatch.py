"""Adopt a staged handoff after the finalizer fixed point succeeds."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedHandoffError,
    StagedRecoveryAttempt,
    acquire_adoption_lock,
    ensure_recovery_context_locked,
    read_adoption_receipt,
    read_staged_successor,
    read_staged_handoff,
    read_staged_handoff_response,
    receipt_authorizes,
    write_adoption_receipt_locked,
)
from sase.axe._run_agent_exec_staged_shared import (
    StagedAdoptionOutcome,
    StagedInlineContinuation,
    read_json_object,
)
from sase.axe.run_agent_exec_staged_adopters import STAGED_HANDOFF_ADOPTERS
from sase.axe.run_agent_exec_staged_custody import (
    mark_custody_transferred,
    persist_origin_custody,
)
from sase.axe.run_agent_exec_staged_settlement import finalizer_settlement_refusal
from sase.axe.run_agent_exec_staged_monitor import cleanup_staged_monitor_handoff


@dataclass(frozen=True)
class _StagedHandoffDispatch:
    """Result of examining and, when safe, adopting one staged handoff."""

    adopted: bool
    outcome: str | None = None
    reason: str | None = None
    already_adopted: bool = False


def _read_run_metadata(artifacts_dir: str) -> dict[str, Any]:
    return read_json_object(
        Path(artifacts_dir) / "agent_meta.json", label="agent metadata"
    )


def _normalize_adopter_result(
    raw: str | None | StagedAdoptionOutcome,
) -> tuple[str | None, str | None, Mapping[str, Any] | None]:
    """Split a legacy or narrow adopter return into outcome, custodian, refs."""
    if isinstance(raw, StagedAdoptionOutcome):
        return raw.outcome, raw.custodian, raw.refs
    return raw, None, None


def _resolve_adoption_custodian(
    *,
    explicit: str | None,
    continuation: StagedInlineContinuation,
    original_artifacts_dir: str,
) -> str:
    """Return the actual custodian identity without guessing from commands."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    state = continuation.state
    successor = getattr(state, "current_artifacts_dir", "") or ""
    if isinstance(successor, str) and successor.strip():
        original = Path(original_artifacts_dir).resolve(strict=False)
        current = Path(successor).resolve(strict=False)
        if str(current) != str(original):
            return str(successor)
    gate_dir = getattr(state, "plan_gate_artifacts_dir", None)
    if isinstance(gate_dir, str) and gate_dir.strip():
        return gate_dir.strip()
    question_gate_dir = getattr(state, "question_gate_artifacts_dir", None)
    if isinstance(question_gate_dir, str) and question_gate_dir.strip():
        return question_gate_dir.strip()
    if isinstance(successor, str) and successor.strip():
        return successor.strip()
    return str(original_artifacts_dir)


def _held_receipt_payload(staged_id: str, reason: str) -> dict[str, Any]:
    return {
        "staged_id": staged_id,
        "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "outcome": "handoff_not_adopted",
        "reason": reason,
    }


def _write_held_receipt_locked(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
) -> None:
    """Write a held receipt while holding the adoption lock.

    Receipt monotonicity is enforced at write time: a racing hold never
    overwrites a matching adopted receipt, and a mismatched staged ID is a
    refusal.
    """
    write_adoption_receipt_locked(
        _held_receipt_payload(staged_id, reason),
        artifacts_dir=artifacts_dir,
    )
    cleanup_staged_monitor_handoff(artifacts_dir, held=True)


def _record_failed_adoption(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None = None,
) -> None:
    """Retain unresolved owner work before making the failed receipt visible."""
    retain_failed_adoption_workspace(
        staged_id,
        reason,
        artifacts_dir=artifacts_dir,
        run_metadata=run_metadata,
        continuation=continuation,
    )
    _write_held_receipt_locked(staged_id, reason, artifacts_dir=artifacts_dir)


def retain_failed_adoption_workspace(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None = None,
    notify_on_retain: bool = False,
) -> None:
    """Settle a failed origin through shared policy, pinning on probe failure."""
    try:
        _retain_failed_adoption_workspace(
            staged_id,
            reason,
            artifacts_dir=artifacts_dir,
            run_metadata=run_metadata,
            continuation=continuation,
            notify_on_retain=notify_on_retain,
        )
    except Exception as exc:  # noqa: BLE001 - also pin before receipt publication.
        try:
            _hold_failed_adoption_claim(
                artifacts_dir=artifacts_dir,
                run_metadata=run_metadata,
                continuation=continuation,
                error=exc,
            )
        except Exception as hold_exc:  # noqa: BLE001 - receipt remains durable.
            print(
                f"Could not pin staged starter after retention error: {hold_exc}",
                file=sys.stderr,
            )


def _hold_failed_adoption_claim(
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None,
    error: Exception,
) -> None:
    """Pin the exact starter claim if policy evidence collection failed."""
    from sase.running_field import get_claimed_workspaces, hold_workspace_claim

    context = getattr(continuation, "ctx", None)
    state = getattr(continuation, "state", None)
    raw_project_file = run_metadata.get("project_file") or os.environ.get(
        "SASE_AGENT_PROJECT_FILE"
    )
    if not raw_project_file:
        raw_project_file = getattr(context, "project_file", None)
    if not isinstance(raw_project_file, str) or not raw_project_file:
        print(
            f"Could not pin staged starter after retention error; "
            f"project identity is unavailable: {error}",
            file=sys.stderr,
        )
        return
    raw_workspace_num = run_metadata.get("workspace_num")
    try:
        workspace_num = int(raw_workspace_num or 0)
    except (TypeError, ValueError):
        workspace_num = 0
    if workspace_num <= 0:
        state_workspace_num = getattr(state, "workspace_num", None)
        workspace_num = (
            state_workspace_num
            if isinstance(state_workspace_num, int)
            and not isinstance(state_workspace_num, bool)
            else 0
        )
    raw_pid = run_metadata.get("pid")
    pid = (
        raw_pid if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) else None
    )
    raw_cl_name = run_metadata.get("cl_name") or run_metadata.get("patch_name")
    cl_name = raw_cl_name if isinstance(raw_cl_name, str) else ""
    if not cl_name:
        context_cl_name = getattr(context, "cl_name", None)
        cl_name = context_cl_name if isinstance(context_cl_name, str) else ""
    workflow_value = run_metadata.get("workflow_name")
    workflow = workflow_value if isinstance(workflow_value, str) else ""
    if not workflow:
        context_workflow = getattr(context, "workflow_name", None)
        workflow = context_workflow if isinstance(context_workflow, str) else ""
    timestamp = Path(artifacts_dir).name
    try:
        candidates = [
            claim
            for claim in get_claimed_workspaces(raw_project_file)
            if claim.workspace_num == workspace_num
            and (claim.cl_name or "") == cl_name
            and (claim.artifacts_timestamp or "") == timestamp
            and (pid is None or claim.pid == pid)
            and (not workflow or claim.workflow == workflow)
        ]
    except Exception as claims_exc:  # noqa: BLE001 - log, never release.
        print(
            f"Could not inspect staged starter claim after retention error: "
            f"{claims_exc}",
            file=sys.stderr,
        )
        return
    if len(candidates) != 1:
        print(
            "Could not pin staged starter after retention error; "
            f"found {len(candidates)} exact claim candidates: {error}",
            file=sys.stderr,
        )
        return
    claim = candidates[0]
    held = hold_workspace_claim(
        raw_project_file,
        claim.workspace_num,
        claim.workflow,
        claim.cl_name or "",
        claim.artifacts_timestamp or "",
        caller_tag="staged-retention-fail-closed",
        expected_pid=claim.pid,
    )
    if not held.success:
        print(
            f"Could not pin staged starter after retention error: "
            f"{held.error or error}",
            file=sys.stderr,
        )


def _retain_failed_adoption_workspace(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation | None,
    notify_on_retain: bool,
) -> None:
    """Apply shared policy to the exact staged starter claim and repositories."""
    from sase.running_field import get_claimed_workspaces
    from sase.turns.workspace_retention import (
        WorkspaceRetentionOwner,
        discover_workspace_retention_repos,
        settle_stranded_workspace,
    )

    raw_workspace_num = run_metadata.get("workspace_num")
    try:
        workspace_num = int(raw_workspace_num or 0)
    except (TypeError, ValueError):
        workspace_num = 0
    context = getattr(continuation, "ctx", None)
    state = getattr(continuation, "state", None)
    if workspace_num <= 0:
        state_workspace_num = getattr(state, "workspace_num", None)
        if isinstance(state_workspace_num, int) and not isinstance(
            state_workspace_num, bool
        ):
            workspace_num = state_workspace_num
    raw_pid = run_metadata.get("pid")
    pid = (
        raw_pid
        if isinstance(raw_pid, int) and not isinstance(raw_pid, bool)
        else os.getpid()
    )
    raw_cl_name = run_metadata.get("cl_name") or run_metadata.get("patch_name")
    cl_name = raw_cl_name if isinstance(raw_cl_name, str) else ""
    if not cl_name:
        context_cl_name = getattr(context, "cl_name", None)
        cl_name = context_cl_name if isinstance(context_cl_name, str) else ""
    artifacts_timestamp = Path(artifacts_dir).name
    raw_project_file = run_metadata.get("project_file") or os.environ.get(
        "SASE_AGENT_PROJECT_FILE"
    )
    if not raw_project_file:
        raw_project_file = getattr(context, "project_file", None)
    if not isinstance(raw_project_file, str) or not raw_project_file:
        raise RuntimeError("staged starter has no project-file identity")
    project_file = raw_project_file
    raw_checkout_dir = run_metadata.get("workspace_dir")
    checkout_dir = raw_checkout_dir if isinstance(raw_checkout_dir, str) else None
    if not checkout_dir:
        state_workspace_dir = getattr(state, "workspace_dir", None)
        checkout_dir = (
            state_workspace_dir if isinstance(state_workspace_dir, str) else None
        )
    raw_workflow = run_metadata.get("workflow_name")
    workflow = raw_workflow if isinstance(raw_workflow, str) else ""
    if not workflow:
        context_workflow = getattr(context, "workflow_name", None)
        workflow = context_workflow if isinstance(context_workflow, str) else ""
    if not workflow:
        claims = get_claimed_workspaces(project_file)
        matching = [
            claim
            for claim in claims
            if claim.workspace_num == workspace_num
            and claim.pid == pid
            and (claim.cl_name or "") == cl_name
            and (claim.artifacts_timestamp or "") == artifacts_timestamp
        ]
        if len(matching) == 1:
            workflow = matching[0].workflow

    repos, origin_repo_ids = discover_workspace_retention_repos(
        artifacts_dir,
        checkout_dir,
    )
    owner = WorkspaceRetentionOwner(
        project_file=project_file,
        workspace_num=workspace_num,
        workflow=workflow,
        cl_name=cl_name,
        artifacts_timestamp=artifacts_timestamp,
        pid=pid,
        artifacts_dir=artifacts_dir,
        checkout_dir=checkout_dir,
        repos=repos,
        origin_repo_ids=origin_repo_ids,
        staged_id=staged_id,
        session_id=(
            str(run_metadata.get("agent_session"))
            if run_metadata.get("agent_session")
            else None
        ),
        turn_id=(str(run_metadata.get("name")) if run_metadata.get("name") else None),
        terminal_reason=reason,
        notify_on_retain=notify_on_retain,
    )
    settle_stranded_workspace(owner)


def _already_adopted_dispatch(
    receipt: Mapping[str, Any],
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    continuation: StagedInlineContinuation,
) -> _StagedHandoffDispatch:
    receipt_refs = receipt.get("refs")
    receipt_refs = receipt_refs if isinstance(receipt_refs, Mapping) else {}
    outcome = receipt_refs.get("loop_outcome")
    if outcome is not None and not isinstance(outcome, str):
        raise StagedHandoffError("staged adoption receipt has an invalid loop outcome")
    if "loop_outcome" not in receipt_refs:
        outcome = "completed"
    if staged_record.get("kind") in {"pipe", "plan", "questions"} and outcome is None:
        staged_id = str(staged_record.get("staged_id") or "")
        successor = read_staged_successor(artifacts_dir, staged_id=staged_id)
        if successor is None:
            if receipt_refs.get("successor_artifacts_dir") is not None:
                return _StagedHandoffDispatch(
                    adopted=False,
                    reason=(
                        "adopted inline receipt references a missing successor identity"
                    ),
                    already_adopted=True,
                )
            return _StagedHandoffDispatch(
                adopted=True,
                outcome=outcome,
                already_adopted=True,
            )
        successor_dir = str(successor["successor"]["artifacts_dir"])
        if receipt_refs.get("successor_artifacts_dir") != successor_dir:
            return _StagedHandoffDispatch(
                adopted=False,
                reason=(
                    "adopted inline receipt does not match the persisted successor"
                ),
                already_adopted=True,
            )
        launch_identity = receipt_refs.get("successor_launch_identity")
        if (
            launch_identity is not None
            and launch_identity != successor["successor"]["launch_identity"]
        ):
            return _StagedHandoffDispatch(
                adopted=False,
                reason="adopted inline receipt has a mismatched launch identity",
                already_adopted=True,
            )
        if successor["delivery_state"] in {"submitted", "started", "terminal"}:
            return _StagedHandoffDispatch(
                adopted=True,
                outcome="completed",
                already_adopted=True,
            )
        try:
            if staged_record.get("kind") == "pipe":
                from sase.axe.run_agent_exec_pipe import restore_staged_pipe_successor

                restore_staged_pipe_successor(continuation.state, successor)
            else:
                from sase.axe.run_agent_successor import (
                    restore_staged_successor_in_loop,
                )

                restore_staged_successor_in_loop(continuation.state, successor)
        except Exception as exc:  # noqa: BLE001 - refuse malformed replay state.
            return _StagedHandoffDispatch(
                adopted=False,
                reason=f"adopted inline successor cannot be restored: {exc}",
                already_adopted=True,
            )
    return _StagedHandoffDispatch(
        adopted=True,
        outcome=outcome,
        already_adopted=True,
    )


def dispatch_completed_staged_handoff(
    artifacts_dir: str,
    continuation: StagedInlineContinuation,
) -> _StagedHandoffDispatch | None:
    """Adopt a staged handoff only after the finalizer fixed point succeeds.

    The shared adoption lock serializes the normal runner, manual recovery,
    and housekeeping callers. The receipt is re-read after acquiring the
    lock: a matching adopted receipt wins, and a malformed or mismatched
    receipt is a refusal, not missing state. The recovery context is
    persisted before any adopter side effect so a dead runner leaves
    reconstructable state.
    """
    staged_record = read_staged_handoff(artifacts_dir)
    if staged_record is None:
        return None
    staged_id = str(staged_record["staged_id"])
    original_artifacts_dir = artifacts_dir

    with acquire_adoption_lock(Path(artifacts_dir)):
        # Revalidate under the lock: a racing success wins without rework.
        staged_record = read_staged_handoff(artifacts_dir)
        if staged_record is None:
            return None
        staged_id = str(staged_record["staged_id"])
        receipt = read_adoption_receipt(artifacts_dir)
        if receipt is not None:
            if receipt_authorizes(receipt, staged_id):
                return _already_adopted_dispatch(
                    receipt,
                    staged_record,
                    artifacts_dir=artifacts_dir,
                    continuation=continuation,
                )
            if str(receipt.get("staged_id")) != staged_id:
                return _StagedHandoffDispatch(
                    adopted=False,
                    reason="existing adoption receipt belongs to a different stage",
                )

        run_metadata = _read_run_metadata(artifacts_dir)
        refusal = finalizer_settlement_refusal(
            staged_record,
            artifacts_dir=artifacts_dir,
            run_metadata=run_metadata,
        )
        if refusal is not None:
            _record_failed_adoption(
                staged_id,
                refusal,
                artifacts_dir=artifacts_dir,
                run_metadata=run_metadata,
                continuation=continuation,
            )
            return _StagedHandoffDispatch(adopted=False, reason=refusal)

        # Settlement is proven: persist origin custody before any adopter
        # runs so a failed adoption leaves origin evidence intact. The
        # response and kind checks come first: held handoffs (missing
        # response or unsupported kind) never need a recovery context, and
        # the recovery contract only accepts known staged kinds.
        persist_origin_custody(
            staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
        )

        response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
        if response is None:
            reason = (
                "ordinary provider response was not persisted for this staged handoff"
            )
            _record_failed_adoption(
                staged_id,
                reason,
                artifacts_dir=artifacts_dir,
                run_metadata=run_metadata,
                continuation=continuation,
            )
            return _StagedHandoffDispatch(adopted=False, reason=reason)

        adopter = STAGED_HANDOFF_ADOPTERS.get(str(staged_record.get("kind")))
        if adopter is None:
            reason = f"unsupported staged handoff kind {staged_record.get('kind')!r}"
            _record_failed_adoption(
                staged_id,
                reason,
                artifacts_dir=artifacts_dir,
                run_metadata=run_metadata,
                continuation=continuation,
            )
            return _StagedHandoffDispatch(adopted=False, reason=reason)

        recovery_context = ensure_recovery_context_locked(
            staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
        )
        attempt = StagedRecoveryAttempt(
            staged_record=staged_record,
            run_metadata=run_metadata,
            recovery_context=recovery_context,
            continuation=continuation,
        )
        live_continuation = attempt.require_live_continuation()

        adapter_record = dict(attempt.staged_record)
        original_state_artifacts_dir = live_continuation.state.current_artifacts_dir
        try:
            if staged_record.get("kind") in {"plan", "questions"}:
                from sase.agent._staged_handoff_approval import (
                    ensure_staged_approval_context_locked,
                )

                adapter_record["approval_context"] = (
                    ensure_staged_approval_context_locked(
                        staged_record,
                        artifacts_dir=artifacts_dir,
                        run_metadata=run_metadata,
                        continuation=live_continuation,
                    )
                )
            raw_outcome = adopter(
                adapter_record,
                attempt.run_metadata,
                live_continuation,
                response,
            )
            outcome, explicit_custodian, extra_refs = _normalize_adopter_result(
                raw_outcome
            )
            if outcome == "plan_rejected":
                reason = "staged plan could not be adopted by the plan approval flow"
                _record_failed_adoption(
                    staged_id,
                    reason,
                    artifacts_dir=original_artifacts_dir,
                    run_metadata=run_metadata,
                    continuation=live_continuation,
                )
                return _StagedHandoffDispatch(adopted=False, reason=reason)
        except Exception as exc:
            _record_failed_adoption(
                staged_id,
                (
                    f"staged {staged_record.get('kind') or 'handoff'} adoption "
                    f"failed: {type(exc).__name__}: {exc}"
                ),
                artifacts_dir=original_artifacts_dir,
                run_metadata=run_metadata,
                continuation=live_continuation,
            )
            raise

        custodian = _resolve_adoption_custodian(
            explicit=explicit_custodian,
            continuation=live_continuation,
            original_artifacts_dir=original_artifacts_dir,
        )
        mark_custody_transferred(
            staged_record,
            artifacts_dir=original_artifacts_dir,
            carried_to=custodian,
        )

        adoption_refs: dict[str, Any] = {"loop_outcome": outcome}
        if extra_refs:
            for key, value in extra_refs.items():
                if value is None or key in adoption_refs:
                    continue
                adoption_refs[key] = value
        if live_continuation.state.plan_gate_artifacts_dir:
            adoption_refs["plan_gate_artifacts_dir"] = (
                live_continuation.state.plan_gate_artifacts_dir
            )
        if (
            live_continuation.state.current_artifacts_dir
            != original_state_artifacts_dir
        ):
            adoption_refs["successor_artifacts_dir"] = (
                live_continuation.state.current_artifacts_dir
            )
        write_adoption_receipt_locked(
            {
                "staged_id": staged_id,
                "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "outcome": "adopted",
                "refs": adoption_refs,
            },
            artifacts_dir=original_artifacts_dir,
        )
    from sase.axe.run_agent_helpers import update_meta_field

    update_meta_field(original_artifacts_dir, "handoff_protocol", "staged")
    return _StagedHandoffDispatch(adopted=True, outcome=outcome)


__all__ = ["dispatch_completed_staged_handoff"]

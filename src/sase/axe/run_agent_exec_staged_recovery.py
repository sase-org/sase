"""One host recovery entry point for every staged-handoff kind.

The normal runner adopts through
``dispatch_completed_staged_handoff`` with a live continuation. This module
is the outside-runner path the ``recovery-service`` phase requires: resolve
the originating artifacts identity plus the persisted recovery context,
serialize with the shared adoption lock, gather current facts, ask the Rust
recovery policy, and dispatch the now-replayable adapters without
fabricating an ``AgentExecContext`` from the recovering shell.

Fully settled turns adopt immediately. Held failed-finalizer turns stay
held until their remaining obligations have authenticated completion
evidence; repair reuses the existing finalizer and commit-reconciliation
paths and this entry point only revalidates through host APIs, never by
stamping old results as success.

The implementation lives in focused modules; this file keeps the historical
``sase.axe.run_agent_exec_staged_recovery`` import surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedHandoffError,
    acquire_adoption_lock,
    ensure_recovery_context_locked,
    read_recovery_context,
    read_staged_handoff,
    read_staged_successor,
)
from sase.axe._run_agent_exec_staged_recovery_shared import (
    SUCCESSOR_KINDS,
    StagedRecoveryResult,
    adopted_destination_refs,
    adopted_stage_needs_delivery,
    classify_receipt,
    read_run_metadata,
    write_held_locked,
)
from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec_staged_recovery_adopt import (
    adopt_gate_detached_locked,
    adopt_monitor_detached_locked,
    adopt_with_live_continuation_locked,
)
from sase.axe.run_agent_exec_staged_recovery_deliver import (
    complete_already_adopted_delivery,
    complete_pending_delivery,
)
from sase.axe.run_agent_exec_staged_recovery_facts import (
    observe_destination,
    observe_runner,
    observe_settlement,
    repair_action_for,
    was_killed_or_discarded,
    workspace_mismatch,
)


_RECOVERY_MODES = ("automatic", "explicit")


def _already_needs_delivery(
    receipt: Mapping[str, Any] | None, kind: str | None
) -> bool:
    return adopted_stage_needs_delivery(receipt, kind)


def recover_staged_handoff(
    artifacts_dir: str,
    mode: str = "automatic",
    continuation: StagedInlineContinuation | None = None,
) -> StagedRecoveryResult:
    """Recover one staged handoff from persisted state.

    *artifacts_dir* names the originating turn. *mode* is ``"automatic"``
    (scheduler/reconciler, requires a proven-dead runner) or ``"explicit"``
    (operator-initiated re-adoption). *continuation* is the live runner
    continuation when the caller is the runner wrapper; every other caller
    passes ``None`` and never gets a fabricated ``AgentExecContext``.
    """
    if mode not in _RECOVERY_MODES:
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="refuse",
            reason=f"unknown recovery mode {mode!r}",
            repair_action="re-run recovery with mode 'automatic' or 'explicit'",
        )
    try:
        staged_record = read_staged_handoff(artifacts_dir)
    except StagedHandoffError as exc:
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="refuse",
            reason=f"malformed staged handoff: {exc}",
        )
    if staged_record is None:
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="refuse",
            reason="no staged handoff is recorded for this turn",
        )
    origin = str(artifacts_dir)
    pending_delivery: tuple[str, str, str | None, str | None] | None = None
    deferred_already: tuple[dict[str, Any], dict[str, Any] | None] | None = None
    origin_agent: str | None = None
    with acquire_adoption_lock(Path(origin), blocking=mode != "automatic") as acquired:
        if not acquired:
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="hold",
                reason="another caller owns the staged adoption lock",
            )
        staged_record = read_staged_handoff(origin)
        if staged_record is None:
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="refuse",
                reason="the staged handoff vanished under the adoption lock",
            )
        staged_id = str(staged_record.get("staged_id") or "")
        kind_value = staged_record.get("kind")
        kind = str(kind_value) if isinstance(kind_value, str) else None
        receipt_state, receipt = classify_receipt(origin, staged_id)
        try:
            run_metadata = read_run_metadata(origin)
        except StagedHandoffError as exc:
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="refuse",
                reason=f"origin agent metadata is unreadable: {exc}",
                repair_action="restore agent_meta.json before re-running recovery",
                kind=kind,
            )
        raw_name = run_metadata.get("name") or run_metadata.get("agent_name")
        origin_agent = str(raw_name) if isinstance(raw_name, str) else None
        if mode == "automatic":
            # Re-observe under the adoption lock. Ineligible automatic probes
            # must not write a held receipt: a live runner or an unfinished
            # finalizer can become eligible on a later housekeeping pass.
            from sase.agent.staged_handoff import decide_recovery

            destination = observe_destination(staged_record, artifacts_dir=origin)
            if _already_needs_delivery(receipt, kind) and destination == "absent":
                destination = "pending"
            settlement = (
                "settled"
                if receipt_state == "adopted"
                else observe_settlement(
                    staged_record, artifacts_dir=origin, run_metadata=run_metadata
                )[0]
            )
            automatic = decide_recovery(
                {
                    "schema_version": 1,
                    "staged_id": staged_id,
                    "receipt": receipt_state,
                    "runner": observe_runner(run_metadata),
                    "killed_or_discarded": was_killed_or_discarded(
                        origin, run_metadata
                    ),
                    "mode": mode,
                    "settlement": settlement,
                    "destination": destination,
                }
            )
            if automatic["action"] not in {"adopt", "deliver_only"}:
                if automatic["action"] == "hold":
                    from sase.axe.run_agent_exec_staged_retention import (
                        retain_dead_staged_origin,
                    )

                    retain_dead_staged_origin(
                        staged_id, str(automatic["reason"]), artifacts_dir=origin
                    )
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=bool(automatic["already_adopted"]),
                    action=str(automatic["action"]),
                    reason=str(automatic["reason"]),
                    kind=kind,
                    origin_agent=origin_agent,
                )
        if receipt_state == "adopted":
            if _already_needs_delivery(receipt, kind):
                deferred_already = (
                    dict(staged_record),
                    dict(receipt) if receipt is not None else None,
                )
            else:
                return StagedRecoveryResult(
                    adopted=True,
                    already_adopted=True,
                    action="adopt",
                    reason="matching success receipt already owns this adoption",
                    kind=kind,
                    origin_agent=origin_agent,
                    destination=adopted_destination_refs(receipt),
                )
        else:
            try:
                recovery_context = read_recovery_context(origin, staged_id=staged_id)
            except StagedHandoffError as exc:
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="refuse",
                    reason=f"staged recovery context is unusable: {exc}",
                    kind=kind,
                    origin_agent=origin_agent,
                )
            if recovery_context is None:
                try:
                    recovery_context = ensure_recovery_context_locked(
                        staged_record, artifacts_dir=origin, run_metadata=run_metadata
                    )
                except StagedHandoffError as exc:
                    return StagedRecoveryResult(
                        adopted=False,
                        already_adopted=False,
                        action="hold",
                        reason=f"insufficient recovery context: {exc}",
                        repair_action=(
                            "re-stage with origin identity before re-running recovery"
                        ),
                        kind=kind,
                        origin_agent=origin_agent,
                    )
            mismatch = workspace_mismatch(run_metadata, recovery_context)
            if mismatch is not None:
                write_held_locked(staged_id, mismatch, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=mismatch,
                    repair_action=(
                        "reconcile workspace ownership before re-running recovery"
                    ),
                    kind=kind,
                    origin_agent=origin_agent,
                )
            runner = observe_runner(run_metadata)
            killed = was_killed_or_discarded(origin, run_metadata)
            settlement, settlement_reason = observe_settlement(
                staged_record, artifacts_dir=origin, run_metadata=run_metadata
            )
            destination = observe_destination(staged_record, artifacts_dir=origin)
            try:
                from sase.agent.staged_handoff import decide_recovery
            except Exception as exc:  # noqa: BLE001 - binding failure holds.
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=f"recovery policy is unavailable: {exc}",
                    kind=kind,
                    origin_agent=origin_agent,
                )
            try:
                decision = decide_recovery(
                    {
                        "schema_version": 1,
                        "staged_id": staged_id,
                        "receipt": receipt_state,
                        "runner": runner,
                        "killed_or_discarded": bool(killed),
                        "mode": mode,
                        "settlement": settlement,
                        "destination": destination,
                    }
                )
            except StagedHandoffError as exc:
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="refuse",
                    reason=f"recovery evidence is malformed: {exc}",
                    kind=kind,
                    origin_agent=origin_agent,
                )
            action = str(decision.get("action") or "hold")
            already_adopted = bool(decision.get("already_adopted"))
            raw_reason = decision.get("reason")
            policy_reason = str(raw_reason) if isinstance(raw_reason, str) else None
            if receipt_state in {"malformed", "mismatched"}:
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="refuse",
                    reason=(
                        policy_reason
                        or "existing receipt is unusable and cannot authorize adoption"
                    ),
                    kind=kind,
                    origin_agent=origin_agent,
                )
            if killed:
                write_held_locked(
                    staged_id,
                    "explicit kill or discard forbids later activation",
                    artifacts_dir=origin,
                )
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="refuse",
                    reason="explicit kill or discard forbids later activation",
                    kind=kind,
                    origin_agent=origin_agent,
                )
            if action == "refuse":
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="refuse",
                    reason=policy_reason or "recovery refused this stage",
                    kind=kind,
                    origin_agent=origin_agent,
                )
            if already_adopted:
                if _already_needs_delivery(receipt, kind):
                    deferred_already = (
                        dict(staged_record),
                        dict(receipt) if receipt is not None else None,
                    )
                else:
                    return StagedRecoveryResult(
                        adopted=True,
                        already_adopted=True,
                        action="adopt",
                        reason="matching success receipt already owns this adoption",
                        kind=kind,
                        origin_agent=origin_agent,
                        destination=adopted_destination_refs(receipt),
                    )
            elif action == "hold" or settlement != "settled":
                reason = settlement_reason or policy_reason or "recovery is not ready"
                write_held_locked(staged_id, reason, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=reason,
                    repair_action=repair_action_for(
                        settlement=settlement,
                        settlement_reason=settlement_reason,
                        runner=runner,
                        mode=mode,
                        kind=kind,
                        destination=destination,
                    ),
                    kind=kind,
                    origin_agent=origin_agent,
                )
            elif action not in {"adopt", "deliver_only"}:
                reason = policy_reason or "recovery is not ready"
                write_held_locked(staged_id, reason, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=reason,
                    repair_action=repair_action_for(
                        settlement=settlement,
                        settlement_reason=settlement_reason,
                        runner=runner,
                        mode=mode,
                        kind=kind,
                        destination=destination,
                    ),
                    kind=kind,
                    origin_agent=origin_agent,
                )
            elif kind in SUCCESSOR_KINDS:
                try:
                    successor_identity = read_staged_successor(
                        origin, staged_id=staged_id
                    )
                except StagedHandoffError:
                    successor_identity = None
                except Exception:  # noqa: BLE001 - unreadable successor holds.
                    successor_identity = None
                if successor_identity is not None:
                    pending_delivery = (origin, staged_id, kind, origin_agent)
                elif continuation is not None:
                    return adopt_with_live_continuation_locked(
                        staged_record=staged_record,
                        run_metadata=run_metadata,
                        continuation=continuation,
                        artifacts_dir=origin,
                        kind=kind,
                        origin_agent=origin_agent,
                    )
                else:
                    reason = "successor identity is missing for detached adoption"
                    write_held_locked(staged_id, reason, artifacts_dir=origin)
                    return StagedRecoveryResult(
                        adopted=False,
                        already_adopted=False,
                        action="hold",
                        reason=reason,
                        repair_action=(
                            "re-run recovery from the live runner continuation"
                        ),
                        kind=kind,
                        origin_agent=origin_agent,
                    )
            elif continuation is not None:
                return adopt_with_live_continuation_locked(
                    staged_record=staged_record,
                    run_metadata=run_metadata,
                    continuation=continuation,
                    artifacts_dir=origin,
                    kind=kind,
                    origin_agent=origin_agent,
                )
            elif kind == "gate":
                return adopt_gate_detached_locked(
                    staged_record=staged_record,
                    run_metadata=run_metadata,
                    artifacts_dir=origin,
                    kind=kind,
                    origin_agent=origin_agent,
                )
            elif kind == "monitor":
                return adopt_monitor_detached_locked(
                    staged_record=staged_record,
                    run_metadata=run_metadata,
                    artifacts_dir=origin,
                    kind=kind,
                    origin_agent=origin_agent,
                )
            else:
                reason = f"unsupported staged handoff kind {kind!r}"
                write_held_locked(staged_id, reason, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=reason,
                    kind=kind,
                    origin_agent=origin_agent,
                )
    if deferred_already is not None:
        return complete_already_adopted_delivery(
            origin, deferred_already, origin_agent=origin_agent, mode=mode
        )
    if pending_delivery is not None:
        return complete_pending_delivery(pending_delivery, mode=mode)
    return StagedRecoveryResult(
        adopted=False,
        already_adopted=False,
        action="hold",
        reason="recovery did not reach an adoption decision",
    )


__all__ = ["StagedRecoveryResult", "recover_staged_handoff"]

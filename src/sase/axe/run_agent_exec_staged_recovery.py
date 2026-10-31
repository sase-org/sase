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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedHandoffError,
    acquire_adoption_lock,
    ensure_recovery_context_locked,
    read_adoption_receipt,
    read_recovery_context,
    read_staged_handoff,
    read_staged_handoff_response,
    read_staged_successor,
    receipt_authorizes,
    write_adoption_receipt_locked,
)
from sase.axe._run_agent_exec_staged_shared import (
    StagedInlineContinuation,
    read_json_object,
)
from sase.axe.run_agent_exec_staged_custody import (
    mark_custody_transferred,
    persist_origin_custody,
)
from sase.axe.run_agent_exec_staged_settlement import finalizer_settlement_refusal
from sase.axe.run_agent_successor import (
    SuccessorDeliveryResult,
    deliver_staged_successor_detached,
)


@dataclass(frozen=True)
class StagedRecoveryResult:
    """Typed outcome of one host recovery attempt."""

    adopted: bool
    already_adopted: bool
    action: str
    reason: str | None = None
    repair_action: str | None = None
    kind: str | None = None
    origin_agent: str | None = None
    destination: dict[str, Any] | None = None


_RECOVERY_MODES = ("automatic", "explicit")
_SUCCESSOR_KINDS = ("pipe", "plan", "questions")


def _held_receipt_payload(staged_id: str, reason: str) -> dict[str, Any]:
    return {
        "staged_id": staged_id,
        "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "outcome": "handoff_not_adopted",
        "reason": reason,
    }


def _read_run_metadata(artifacts_dir: str) -> dict[str, Any]:
    return read_json_object(
        Path(artifacts_dir) / "agent_meta.json", label="agent metadata"
    )


def _classify_receipt(
    artifacts_dir: str, staged_id: str
) -> tuple[str, dict[str, Any] | None]:
    """Return the Rust receipt wire state plus the receipt when readable."""
    try:
        receipt = read_adoption_receipt(artifacts_dir)
    except StagedHandoffError:
        return "malformed", None
    if receipt is None:
        return "absent", None
    if str(receipt.get("staged_id")) != staged_id:
        return "mismatched", receipt
    try:
        if receipt_authorizes(receipt, staged_id):
            return "adopted", receipt
    except StagedHandoffError:
        return "malformed", receipt
    if receipt.get("outcome") == "handoff_not_adopted":
        return "held", receipt
    return "malformed", receipt


def _observe_runner(run_metadata: Mapping[str, Any]) -> str:
    """Return the Rust runner wire state for persisted process evidence."""
    pid = run_metadata.get("pid")
    if type(pid) is not int or pid <= 0:
        return "unknown"
    identity = run_metadata.get("process_identity")
    try:
        from sase.agent.process_tree import process_is_running
        from sase.core.process_identity import process_identity_matches
    except Exception:  # noqa: BLE001 - unreadable platform helpers are unknown.
        return "unknown"
    try:
        if not process_is_running(pid):
            return "dead"
        if process_identity_matches(pid, identity):
            return "alive"
    except Exception:  # noqa: BLE001 - probing must not fail recovery.
        return "unknown"
    return "unknown"


def _was_killed_or_discarded(
    artifacts_dir: str, run_metadata: Mapping[str, Any]
) -> bool:
    if run_metadata.get("handoff_protocol") == "killed":
        return True
    try:
        from sase.agent._user_kill_intent import has_user_kill_intent
    except Exception:  # noqa: BLE001 - missing helper is not kill evidence.
        return False
    try:
        return bool(has_user_kill_intent(artifacts_dir))
    except Exception:  # noqa: BLE001 - unreadable marker is not kill evidence.
        return False


def _observe_settlement(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Return ``(wire_state, refusal)`` for finalizer settlement proof."""
    root = Path(artifacts_dir)
    if not (root / "finalizer_result.json").is_file():
        return "missing", "finalizer result is missing for this stage"
    try:
        refusal = finalizer_settlement_refusal(
            staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
        )
    except StagedHandoffError as exc:
        return "missing", f"finalizer settlement evidence is unreadable: {exc}"
    except Exception as exc:  # noqa: BLE001 - malformed proof holds adoption.
        return "missing", f"finalizer settlement evidence is unreadable: {exc}"
    if refusal is None:
        return "settled", None
    if "missing" in refusal or "absent" in refusal or "unreadable" in refusal:
        return "missing", refusal
    return "held", refusal


def _observe_destination(
    staged_record: Mapping[str, Any], *, artifacts_dir: str
) -> str:
    """Return the Rust destination wire state for durable effects."""
    kind = staged_record.get("kind")
    if kind not in _SUCCESSOR_KINDS:
        return "absent"
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return "absent"
    try:
        successor = read_staged_successor(artifacts_dir, staged_id=staged_id)
    except StagedHandoffError:
        return "absent"
    except Exception:  # noqa: BLE001 - unreadable successor is not an effect.
        return "absent"
    if successor is None:
        return "absent"
    state = str(successor.get("delivery_state") or "")
    if state == "terminal":
        return "terminal"
    if state in {"submitted", "started", "created", "prepared", "owned"}:
        return "pending" if state != "owned" else "owned"
    return "pending"


def _repair_action_for(
    *,
    settlement: str,
    settlement_reason: str | None,
    runner: str,
    mode: str,
    kind: str | None,
    destination: str,
) -> str | None:
    if settlement in {"missing", "held"} and settlement_reason:
        lowered = settlement_reason.lower()
        if "declaration" in lowered or "submission" in lowered:
            return "complete the accepted final declaration, then re-run recovery"
        if "commit" in lowered or "repository" in lowered or "repo" in lowered:
            return "repair the unfinished commit finalizer work, then re-run recovery"
        if "carry" in lowered or "prepared" in lowered or "deferral" in lowered:
            return "retain carry/prepared proof and settle the remaining work first"
        if "provider response" in lowered or "ordinary provider" in lowered:
            return "recovery requires the persisted provider response"
        if "workspace" in lowered:
            return "reconcile workspace ownership before re-running recovery"
        return "settle the remaining finalizer obligations, then re-run recovery"
    if runner == "alive" and mode == "automatic":
        return "wait for the live runner or re-run recovery explicitly after it dies"
    if runner == "unknown":
        return "prove the originating runner is dead, then re-run recovery"
    if destination == "pending" and kind in _SUCCESSOR_KINDS:
        return "re-run recovery to deliver the recorded successor exactly once"
    return None


def _workspace_mismatch(
    run_metadata: Mapping[str, Any], recovery_context: Mapping[str, Any]
) -> str | None:
    expected = recovery_context.get("workspace_dir")
    observed = run_metadata.get("workspace_dir")
    if (
        isinstance(expected, str)
        and expected.strip()
        and isinstance(observed, str)
        and observed.strip()
        and Path(expected).resolve(strict=False) != Path(observed).resolve(strict=False)
    ):
        return "persisted workspace ownership changed since the stage was recorded"
    return None


def _adopted_destination_refs(
    receipt: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(receipt, Mapping):
        return None
    refs = receipt.get("refs")
    return dict(refs) if isinstance(refs, Mapping) else {}


def _already_needs_delivery(
    receipt: Mapping[str, Any] | None, kind: str | None
) -> bool:
    if kind not in _SUCCESSOR_KINDS:
        return False
    refs = _adopted_destination_refs(receipt)
    successor_dir = (refs or {}).get("successor_artifacts_dir")
    return isinstance(successor_dir, str) and bool(successor_dir)


def _delivery_to_held(
    delivery: SuccessorDeliveryResult,
    *,
    kind: str | None,
    origin_agent: str | None,
) -> StagedRecoveryResult:
    destination: dict[str, Any] = {
        "successor_artifacts_dir": delivery.artifacts_dir,
        "successor_agent": delivery.agent_name,
    }
    if delivery.pid is not None:
        destination["pid"] = delivery.pid
    return StagedRecoveryResult(
        adopted=False,
        already_adopted=True,
        action="hold",
        reason=delivery.reason or "adopted successor delivery is pending",
        repair_action=delivery.reason,
        kind=kind,
        origin_agent=origin_agent,
        destination=destination,
    )


def _write_held_locked(staged_id: str, reason: str, *, artifacts_dir: str) -> None:
    from sase.axe.run_agent_exec_staged_monitor import cleanup_staged_monitor_handoff

    try:
        write_adoption_receipt_locked(
            _held_receipt_payload(staged_id, reason),
            artifacts_dir=artifacts_dir,
        )
    except StagedHandoffError:
        return
    cleanup_staged_monitor_handoff(artifacts_dir, held=True)


def _write_adopted_locked(
    *,
    staged_id: str,
    refs: Mapping[str, Any],
    artifacts_dir: str,
) -> None:
    write_adoption_receipt_locked(
        {
            "staged_id": staged_id,
            "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "outcome": "adopted",
            "refs": dict(refs),
        },
        artifacts_dir=artifacts_dir,
    )


def _split_adopter_result(
    raw: str | None | Any,
) -> tuple[str | None, str | None, Mapping[str, Any] | None]:
    """Split a legacy or narrow adopter return into outcome, custodian, refs."""
    from sase.axe._run_agent_exec_staged_shared import StagedAdoptionOutcome

    if isinstance(raw, StagedAdoptionOutcome):
        return raw.outcome, raw.custodian, raw.refs
    return raw, None, None


def _adoption_custodian(
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


def _adopt_with_live_continuation_locked(
    *,
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    continuation: StagedInlineContinuation,
    artifacts_dir: str,
    kind: str | None,
    origin_agent: str | None,
) -> StagedRecoveryResult:
    """Adopt while holding the adoption lock with a live continuation."""
    from sase.axe.run_agent_exec_staged_adopters import STAGED_HANDOFF_ADOPTERS

    staged_id = str(staged_record.get("staged_id") or "")
    persist_origin_custody(
        staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
    )
    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is None:
        reason = "ordinary provider response was not persisted for this staged handoff"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    adopter = STAGED_HANDOFF_ADOPTERS.get(str(staged_record.get("kind")))
    if adopter is None:
        reason = f"unsupported staged handoff kind {staged_record.get('kind')!r}"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    try:
        from sase.agent._staged_handoff_recovery import StagedRecoveryAttempt

        attempt_context = ensure_recovery_context_locked(
            staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
        )
        attempt = StagedRecoveryAttempt(
            staged_record=staged_record,
            run_metadata=run_metadata,
            recovery_context=attempt_context,
            continuation=continuation,
        )
        live_continuation = attempt.require_live_continuation()
        adapter_record = dict(attempt.staged_record)
        if staged_record.get("kind") in {"plan", "questions"}:
            from sase.agent._staged_handoff_approval import (
                ensure_staged_approval_context_locked,
            )

            adapter_record["approval_context"] = ensure_staged_approval_context_locked(
                staged_record,
                artifacts_dir=artifacts_dir,
                run_metadata=run_metadata,
                continuation=live_continuation,
            )
        raw_outcome = adopter(
            adapter_record, attempt.run_metadata, live_continuation, response
        )
        outcome, explicit_custodian, extra_refs = _split_adopter_result(raw_outcome)
        if outcome == "plan_rejected":
            reason = "staged plan could not be adopted by the plan approval flow"
            _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="hold",
                reason=reason,
                kind=kind,
                origin_agent=origin_agent,
            )
    except Exception as exc:
        _write_held_locked(
            staged_id,
            (
                f"staged {staged_record.get('kind') or 'handoff'} adoption "
                f"failed: {type(exc).__name__}: {exc}"
            ),
            artifacts_dir=artifacts_dir,
        )
        raise
    custodian = _adoption_custodian(
        explicit=explicit_custodian,
        continuation=live_continuation,
        original_artifacts_dir=artifacts_dir,
    )
    mark_custody_transferred(
        staged_record, artifacts_dir=artifacts_dir, carried_to=custodian
    )
    refs: dict[str, Any] = {"loop_outcome": outcome}
    if extra_refs:
        for key, value in extra_refs.items():
            if value is None or key in refs:
                continue
            refs[key] = value
    if live_continuation.state.plan_gate_artifacts_dir:
        refs["plan_gate_artifacts_dir"] = (
            live_continuation.state.plan_gate_artifacts_dir
        )
    _write_adopted_locked(staged_id=staged_id, refs=refs, artifacts_dir=artifacts_dir)
    return StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        kind=kind,
        origin_agent=origin_agent,
        destination=dict(refs),
    )


def _adopt_gate_detached_locked(
    *,
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    artifacts_dir: str,
    kind: str | None,
    origin_agent: str | None,
) -> StagedRecoveryResult:
    """Adopt a staged gate without a live continuation."""
    from sase.gate_turn.publisher import publish_staged_gate

    staged_id = str(staged_record.get("staged_id") or "")
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        reason = "staged gate payload is malformed"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    persist_origin_custody(
        staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
    )
    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is None:
        reason = "ordinary provider response was not persisted for this staged handoff"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    try:
        creation = publish_staged_gate(
            payload, staged_id=staged_id, artifacts_dir=artifacts_dir
        )
    except Exception as exc:
        reason = f"staged gate publication failed: {type(exc).__name__}: {exc}"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            repair_action="repair gate publication evidence, then re-run recovery",
            kind=kind,
            origin_agent=origin_agent,
        )
    custodian = creation.record.artifacts_dir
    mark_custody_transferred(
        staged_record, artifacts_dir=artifacts_dir, carried_to=custodian
    )
    refs: dict[str, Any] = {
        "gate_id": creation.record.gate_id,
        "gate_request_id": creation.gate.request_id or creation.record.gate_id,
        "member_artifacts_dir": creation.record.artifacts_dir,
    }
    if isinstance(creation.gate.notification_id, str):
        refs["notification_id"] = creation.gate.notification_id
    _write_adopted_locked(staged_id=staged_id, refs=refs, artifacts_dir=artifacts_dir)
    return StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        kind=kind,
        origin_agent=origin_agent,
        destination=dict(refs),
    )


def _adopt_monitor_detached_locked(
    *,
    staged_record: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
    artifacts_dir: str,
    kind: str | None,
    origin_agent: str | None,
) -> StagedRecoveryResult:
    """Adopt a staged monitor without a live continuation."""
    staged_id = str(staged_record.get("staged_id") or "")
    payload = staged_record.get("payload")
    if not isinstance(payload, Mapping):
        reason = "staged monitor payload is malformed"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    monitor_id = payload.get("monitor_id")
    if not isinstance(monitor_id, str) or not monitor_id:
        reason = "staged monitor payload has no monitor_id"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    persist_origin_custody(
        staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
    )
    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is None:
        reason = "ordinary provider response was not persisted for this staged handoff"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    try:
        from sase.monitor.staged_owner import read_staged_owner_index
    except Exception as exc:  # noqa: BLE001 - missing helper holds recovery.
        reason = f"staged monitor owner index is unavailable: {exc}"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    try:
        index = read_staged_owner_index(monitor_id)
    except Exception:  # noqa: BLE001 - missing index is a hold, not a crash.
        index = None
    member_dir: str | None = None
    if isinstance(index, Mapping) and index.get("staged_id") == staged_id:
        candidate = index.get("artifacts_dir")
        if isinstance(candidate, str) and candidate.strip():
            member_dir = candidate.strip()
    if member_dir is None:
        reason = (
            f"staged monitor member is unknown for monitor {monitor_id!r} "
            f"stage {staged_id!r}"
        )
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            kind=kind,
            origin_agent=origin_agent,
        )
    try:
        from sase.monitor.start_stage_adopt import launch_from_persisted_payload

        record = launch_from_persisted_payload(member_dir)
    except Exception as exc:
        reason = f"staged monitor launch failed: {type(exc).__name__}: {exc}"
        _write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
        return StagedRecoveryResult(
            adopted=False,
            already_adopted=False,
            action="hold",
            reason=reason,
            repair_action="repair monitor launch evidence, then re-run recovery",
            kind=kind,
            origin_agent=origin_agent,
        )
    mark_custody_transferred(
        staged_record, artifacts_dir=artifacts_dir, carried_to=record.artifacts_dir
    )
    refs: dict[str, Any] = {
        "monitor_id": record.monitor_id,
        "member_artifacts_dir": record.artifacts_dir,
        "staged_id": staged_id,
    }
    _write_adopted_locked(staged_id=staged_id, refs=refs, artifacts_dir=artifacts_dir)
    return StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        kind=kind,
        origin_agent=origin_agent,
        destination=dict(refs),
    )


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
    with acquire_adoption_lock(Path(origin)):
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
        receipt_state, receipt = _classify_receipt(origin, staged_id)
        try:
            run_metadata = _read_run_metadata(origin)
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
                    destination=_adopted_destination_refs(receipt),
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
            mismatch = _workspace_mismatch(run_metadata, recovery_context)
            if mismatch is not None:
                _write_held_locked(staged_id, mismatch, artifacts_dir=origin)
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
            runner = _observe_runner(run_metadata)
            killed = _was_killed_or_discarded(origin, run_metadata)
            settlement, settlement_reason = _observe_settlement(
                staged_record, artifacts_dir=origin, run_metadata=run_metadata
            )
            destination = _observe_destination(staged_record, artifacts_dir=origin)
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
                _write_held_locked(
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
                        destination=_adopted_destination_refs(receipt),
                    )
            elif action == "hold" or settlement != "settled":
                reason = settlement_reason or policy_reason or "recovery is not ready"
                _write_held_locked(staged_id, reason, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=reason,
                    repair_action=_repair_action_for(
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
                _write_held_locked(staged_id, reason, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=reason,
                    repair_action=_repair_action_for(
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
            elif kind in _SUCCESSOR_KINDS:
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
                    return _adopt_with_live_continuation_locked(
                        staged_record=staged_record,
                        run_metadata=run_metadata,
                        continuation=continuation,
                        artifacts_dir=origin,
                        kind=kind,
                        origin_agent=origin_agent,
                    )
                else:
                    reason = "successor identity is missing for detached adoption"
                    _write_held_locked(staged_id, reason, artifacts_dir=origin)
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
                return _adopt_with_live_continuation_locked(
                    staged_record=staged_record,
                    run_metadata=run_metadata,
                    continuation=continuation,
                    artifacts_dir=origin,
                    kind=kind,
                    origin_agent=origin_agent,
                )
            elif kind == "gate":
                return _adopt_gate_detached_locked(
                    staged_record=staged_record,
                    run_metadata=run_metadata,
                    artifacts_dir=origin,
                    kind=kind,
                    origin_agent=origin_agent,
                )
            elif kind == "monitor":
                return _adopt_monitor_detached_locked(
                    staged_record=staged_record,
                    run_metadata=run_metadata,
                    artifacts_dir=origin,
                    kind=kind,
                    origin_agent=origin_agent,
                )
            else:
                reason = f"unsupported staged handoff kind {kind!r}"
                _write_held_locked(staged_id, reason, artifacts_dir=origin)
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=reason,
                    kind=kind,
                    origin_agent=origin_agent,
                )
    if deferred_already is not None:
        staged_snapshot, receipt_snapshot = deferred_already
        snapshot_id = str(staged_snapshot.get("staged_id") or "")
        snapshot_kind_value = staged_snapshot.get("kind")
        snapshot_kind = (
            str(snapshot_kind_value) if isinstance(snapshot_kind_value, str) else None
        )
        with acquire_adoption_lock(Path(origin)):
            check_agent_value = _read_run_metadata(origin).get("name")
            check_agent = (
                str(check_agent_value)
                if isinstance(check_agent_value, str)
                else origin_agent
            )
        delivery = deliver_staged_successor_detached(origin, snapshot_id)
        if delivery.state in {"submitted", "owned", "terminal"}:
            already_destination = _adopted_destination_refs(receipt_snapshot) or {}
            already_destination.setdefault(
                "successor_artifacts_dir", delivery.artifacts_dir
            )
            return StagedRecoveryResult(
                adopted=True,
                already_adopted=True,
                action="adopt",
                reason="matching success receipt already owns this adoption",
                kind=snapshot_kind,
                origin_agent=check_agent,
                destination=already_destination,
            )
        return _delivery_to_held(delivery, kind=snapshot_kind, origin_agent=check_agent)
    if pending_delivery is not None:
        pending_origin, pending_staged_id, pending_kind, pending_agent = (
            pending_delivery
        )
        delivery = deliver_staged_successor_detached(pending_origin, pending_staged_id)
        if delivery.state not in {"submitted", "owned", "terminal"}:
            hold_destination: dict[str, Any] = {
                "successor_artifacts_dir": delivery.artifacts_dir,
                "successor_agent": delivery.agent_name,
            }
            if delivery.pid is not None:
                hold_destination["pid"] = delivery.pid
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="hold",
                reason=delivery.reason or "successor delivery is still pending",
                repair_action=delivery.reason,
                kind=pending_kind,
                origin_agent=pending_agent,
                destination=hold_destination,
            )
        with acquire_adoption_lock(Path(pending_origin)):
            current = read_staged_handoff(pending_origin)
            if current is None or str(current.get("staged_id")) != pending_staged_id:
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="refuse",
                    reason="the staged handoff changed during detached delivery",
                    kind=pending_kind,
                    origin_agent=pending_agent,
                )
            existing_state, _existing = _classify_receipt(
                pending_origin, pending_staged_id
            )
            if existing_state == "adopted":
                existing = read_adoption_receipt(pending_origin)
                return StagedRecoveryResult(
                    adopted=True,
                    already_adopted=True,
                    action="adopt",
                    reason="matching success receipt already owns this adoption",
                    kind=pending_kind,
                    origin_agent=pending_agent,
                    destination=_adopted_destination_refs(existing),
                )
            refs: dict[str, Any] = {
                "successor_artifacts_dir": delivery.artifacts_dir,
            }
            try:
                successor_record = read_staged_successor(
                    pending_origin, staged_id=pending_staged_id
                )
            except StagedHandoffError:
                successor_record = None
            except Exception:  # noqa: BLE001 - keep the delivered identity.
                successor_record = None
            if successor_record is not None:
                child = successor_record.get("successor", {})
                if isinstance(child, Mapping):
                    launch_identity = child.get("launch_identity")
                    prompt_ref = child.get("prompt_ref")
                    if launch_identity is not None:
                        refs["successor_launch_identity"] = launch_identity
                    if prompt_ref is not None:
                        refs["successor_prompt_ref"] = prompt_ref
            try:
                persist_origin_custody(
                    current,
                    artifacts_dir=pending_origin,
                    run_metadata=_read_run_metadata(pending_origin),
                )
            except StagedHandoffError:
                pass
            mark_custody_transferred(
                current,
                artifacts_dir=pending_origin,
                carried_to=delivery.artifacts_dir,
            )
            try:
                _write_adopted_locked(
                    staged_id=pending_staged_id,
                    refs=refs,
                    artifacts_dir=pending_origin,
                )
            except StagedHandoffError as exc:
                return StagedRecoveryResult(
                    adopted=False,
                    already_adopted=False,
                    action="hold",
                    reason=f"detached delivery succeeded but the receipt held: {exc}",
                    repair_action="re-run recovery to reconcile the receipt",
                    kind=pending_kind,
                    origin_agent=pending_agent,
                    destination=dict(refs),
                )
            return StagedRecoveryResult(
                adopted=True,
                already_adopted=False,
                action="adopt",
                kind=pending_kind,
                origin_agent=pending_agent,
                destination=dict(refs),
            )
    return StagedRecoveryResult(
        adopted=False,
        already_adopted=False,
        action="hold",
        reason="recovery did not reach an adoption decision",
    )


__all__ = ["StagedRecoveryResult", "recover_staged_handoff"]

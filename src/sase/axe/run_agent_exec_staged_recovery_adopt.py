"""Locked adopters for staged-handoff host recovery."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    ensure_recovery_context_locked,
    read_staged_handoff_response,
)
from sase.axe._run_agent_exec_staged_recovery_shared import (
    StagedRecoveryResult,
    write_adopted_locked,
    write_held_locked,
)
from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec_staged_custody import (
    mark_custody_transferred,
    persist_origin_custody,
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


def adopt_with_live_continuation_locked(
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
            write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
            return StagedRecoveryResult(
                adopted=False,
                already_adopted=False,
                action="hold",
                reason=reason,
                kind=kind,
                origin_agent=origin_agent,
            )
    except Exception as exc:
        write_held_locked(
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
    write_adopted_locked(staged_id=staged_id, refs=refs, artifacts_dir=artifacts_dir)
    return StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        kind=kind,
        origin_agent=origin_agent,
        destination=dict(refs),
    )


def adopt_gate_detached_locked(
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
    write_adopted_locked(staged_id=staged_id, refs=refs, artifacts_dir=artifacts_dir)
    return StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        kind=kind,
        origin_agent=origin_agent,
        destination=dict(refs),
    )


def adopt_monitor_detached_locked(
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
        write_held_locked(staged_id, reason, artifacts_dir=artifacts_dir)
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
    write_adopted_locked(staged_id=staged_id, refs=refs, artifacts_dir=artifacts_dir)
    return StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        kind=kind,
        origin_agent=origin_agent,
        destination=dict(refs),
    )


__all__ = [
    "adopt_gate_detached_locked",
    "adopt_monitor_detached_locked",
    "adopt_with_live_continuation_locked",
]

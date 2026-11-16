"""Adopt a staged handoff after the finalizer fixed point succeeds."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedRecoveryAttempt,
    acquire_adoption_lock,
    build_provider_failure_fallback_response,
    ensure_recovery_context_locked,
    read_adoption_receipt,
    read_provider_failure_record,
    read_staged_handoff,
    read_staged_handoff_response,
    receipt_authorizes,
    write_adoption_receipt_locked,
)
from sase.axe._run_agent_exec_staged_shared import (
    StagedAdoptionOutcome,
    StagedHandoffDispatch,
    StagedInlineContinuation,
    read_json_object,
)
from sase.axe.run_agent_exec_staged_adopters import STAGED_HANDOFF_ADOPTERS
from sase.axe.run_agent_exec_staged_custody import (
    mark_custody_transferred,
    persist_origin_custody,
)
from sase.axe.run_agent_exec_staged_dispatch_replay import already_adopted_dispatch
from sase.axe.run_agent_exec_staged_monitor import cleanup_staged_monitor_handoff
from sase.axe.run_agent_exec_staged_retention import retain_failed_adoption_workspace
from sase.axe.run_agent_exec_staged_settlement import finalizer_settlement_refusal


def _read_run_metadata(artifacts_dir: str) -> dict[str, Any]:
    return read_json_object(
        Path(artifacts_dir) / "agent_meta.json", label="agent metadata"
    )


def _adoptable_staged_response(
    staged_id: str,
    *,
    artifacts_dir: str,
) -> str | None:
    """Return the staged response, falling back to the failure record.

    The response read goes through this module's ``read_staged_handoff_response``
    global so existing test seams keep working. Stages stranded with only
    ``.sase_provider_failure.json`` synthesize a marked fallback reply so they
    stay re-adoptable.
    """
    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is not None:
        return response
    failure = read_provider_failure_record(artifacts_dir)
    if failure is None:
        return None
    return build_provider_failure_fallback_response(failure)


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


def dispatch_completed_staged_handoff(
    artifacts_dir: str,
    continuation: StagedInlineContinuation,
) -> StagedHandoffDispatch | None:
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
                try:
                    from sase.agent.hijack.runner_boundaries import (
                        moot_runner_latch_at_run_end as _moot_latch,
                    )

                    _moot_latch(artifacts_dir, "handoff")
                except Exception:
                    pass
                try:
                    from sase.agent.hijack.runner_boundaries import (
                        enforce_adoption_replay_latch as _enforce_replay,
                    )

                    _enforce_replay(artifacts_dir)
                except Exception as replay_exc:
                    from sase.agent.hijack.spawn_guard import (
                        HijackLatchedError as _ReplayLatched,
                    )

                    if isinstance(replay_exc, _ReplayLatched):
                        raise
                return already_adopted_dispatch(
                    receipt,
                    staged_record,
                    artifacts_dir=artifacts_dir,
                    continuation=continuation,
                )
            if str(receipt.get("staged_id")) != staged_id:
                return StagedHandoffDispatch(
                    adopted=False,
                    reason="existing adoption receipt belongs to a different stage",
                )
            try:
                from sase.agent.hijack.runner_boundaries import (
                    enforce_adoption_replay_latch as _enforce_held_replay,
                )

                _enforce_held_replay(artifacts_dir)
            except Exception as held_exc:
                from sase.agent.hijack.spawn_guard import (
                    HijackLatchedError as _HeldLatched,
                )

                if isinstance(held_exc, _HeldLatched):
                    raise

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
            return StagedHandoffDispatch(adopted=False, reason=refusal)

        # Settlement is proven: persist origin custody before any adopter
        # runs so a failed adoption leaves origin evidence intact. The
        # response and kind checks come first: held handoffs (missing
        # response or unsupported kind) never need a recovery context, and
        # the recovery contract only accepts known staged kinds.
        persist_origin_custody(
            staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
        )

        response = _adoptable_staged_response(staged_id, artifacts_dir=artifacts_dir)
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
            return StagedHandoffDispatch(adopted=False, reason=reason)

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
            return StagedHandoffDispatch(adopted=False, reason=reason)

        try:
            from sase.agent.hijack.runner_boundaries import (
                enforce_staged_adoption_latch as _enforce_adoption,
            )

            _enforce_adoption(
                artifacts_dir,
                staged_id,
                str(staged_record.get("kind") or "staged"),
            )
        except Exception as latch_exc:
            from sase.agent.hijack.spawn_guard import (
                HijackLatchedError as _AdoptLatched,
            )

            if isinstance(latch_exc, _AdoptLatched):
                hijack_ref = latch_exc.hijack_id or "unknown"
                _write_held_receipt_locked(
                    staged_id,
                    f"hijack latch {hijack_ref} suppressed staged "
                    f"{staged_record.get('kind') or 'handoff'} adoption; "
                    "suppressed payload retained and never replayed",
                    artifacts_dir=artifacts_dir,
                )
                raise

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
                return StagedHandoffDispatch(adopted=False, reason=reason)
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
    return StagedHandoffDispatch(adopted=True, outcome=outcome)


__all__ = ["dispatch_completed_staged_handoff", "retain_failed_adoption_workspace"]

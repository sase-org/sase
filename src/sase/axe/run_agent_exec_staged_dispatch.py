"""Adopt a staged handoff after the finalizer fixed point succeeds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import (
    StagedHandoffError,
    read_adoption_receipt,
    read_staged_handoff,
    read_staged_handoff_response,
    receipt_authorizes,
    write_adoption_receipt,
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


def _write_held_receipt(
    staged_id: str,
    reason: str,
    *,
    artifacts_dir: str,
) -> None:
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "outcome": "handoff_not_adopted",
            "reason": reason,
        },
        artifacts_dir=artifacts_dir,
    )


def dispatch_completed_staged_handoff(
    artifacts_dir: str,
    continuation: StagedInlineContinuation,
) -> _StagedHandoffDispatch | None:
    """Adopt a staged handoff only after the finalizer fixed point succeeds."""
    staged_record = read_staged_handoff(artifacts_dir)
    if staged_record is None:
        return None
    staged_id = str(staged_record["staged_id"])

    receipt = read_adoption_receipt(artifacts_dir)
    if receipt is not None and receipt_authorizes(receipt, staged_id):
        receipt_refs = receipt.get("refs")
        receipt_refs = receipt_refs if isinstance(receipt_refs, Mapping) else {}
        outcome = receipt_refs.get("loop_outcome")
        if outcome is not None and not isinstance(outcome, str):
            raise StagedHandoffError(
                "staged adoption receipt has an invalid loop outcome"
            )
        if "loop_outcome" not in receipt_refs:
            outcome = "completed"
        return _StagedHandoffDispatch(
            adopted=True,
            outcome=outcome,
            already_adopted=True,
        )

    run_metadata = _read_run_metadata(artifacts_dir)
    refusal = finalizer_settlement_refusal(
        staged_record,
        artifacts_dir=artifacts_dir,
        run_metadata=run_metadata,
    )
    if refusal is not None:
        _write_held_receipt(staged_id, refusal, artifacts_dir=artifacts_dir)
        return _StagedHandoffDispatch(adopted=False, reason=refusal)

    # Settlement is proven: persist origin custody before any adopter runs so
    # a failed adoption leaves origin evidence intact.
    persist_origin_custody(
        staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
    )

    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is None:
        reason = "ordinary provider response was not persisted for this staged handoff"
        _write_held_receipt(staged_id, reason, artifacts_dir=artifacts_dir)
        return _StagedHandoffDispatch(adopted=False, reason=reason)

    adopter = STAGED_HANDOFF_ADOPTERS.get(str(staged_record.get("kind")))
    if adopter is None:
        reason = f"unsupported staged handoff kind {staged_record.get('kind')!r}"
        _write_held_receipt(staged_id, reason, artifacts_dir=artifacts_dir)
        return _StagedHandoffDispatch(adopted=False, reason=reason)

    original_artifacts_dir = artifacts_dir
    original_state_artifacts_dir = continuation.state.current_artifacts_dir
    try:
        raw_outcome = adopter(staged_record, run_metadata, continuation, response)
        outcome, explicit_custodian, extra_refs = _normalize_adopter_result(raw_outcome)
        if outcome == "plan_rejected":
            reason = "staged plan could not be adopted by the plan approval flow"
            _write_held_receipt(staged_id, reason, artifacts_dir=original_artifacts_dir)
            return _StagedHandoffDispatch(adopted=False, reason=reason)
    except Exception as exc:
        _write_held_receipt(
            staged_id,
            (
                f"staged {staged_record.get('kind') or 'handoff'} adoption "
                f"failed: {type(exc).__name__}: {exc}"
            ),
            artifacts_dir=original_artifacts_dir,
        )
        raise

    custodian = _resolve_adoption_custodian(
        explicit=explicit_custodian,
        continuation=continuation,
        original_artifacts_dir=original_artifacts_dir,
    )
    mark_custody_transferred(
        staged_record, artifacts_dir=original_artifacts_dir, carried_to=custodian
    )

    adoption_refs: dict[str, Any] = {"loop_outcome": outcome}
    if extra_refs:
        for key, value in extra_refs.items():
            if value is None or key in adoption_refs:
                continue
            adoption_refs[key] = value
    if continuation.state.plan_gate_artifacts_dir:
        adoption_refs["plan_gate_artifacts_dir"] = (
            continuation.state.plan_gate_artifacts_dir
        )
    if continuation.state.current_artifacts_dir != original_state_artifacts_dir:
        adoption_refs["successor_artifacts_dir"] = (
            continuation.state.current_artifacts_dir
        )
    write_adoption_receipt(
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

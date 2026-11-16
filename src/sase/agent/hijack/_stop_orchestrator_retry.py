"""Retry a ``stop_blocked`` hijack without starting a second stop."""

from __future__ import annotations

from typing import Any

from sase.agent.hijack._stop_models import HijackTarget, StopDeps
from sase.agent.hijack._stop_orchestrator_common import (
    EXIT_FAILED,
    HijackStopResult,
    build_stop_blocked_result,
    settle_held_result,
    terminate_with_retry,
)


def retry_stop_blocked(
    name: str,
    active: dict[str, Any],
    *,
    subject: Any,
    target: HijackTarget,
    reason: str | None,
    source: str,
    deps: StopDeps,
    decision: dict[str, Any] | None = None,
) -> HijackStopResult:
    """Retry a ``stop_blocked`` target without starting a second stop."""
    from sase.agent.hijack import ledger

    hijack_id = str(active.get("hijack_id") or "")
    try:
        record = ledger.cas_advance_record(active, {"event": "retry_stop"})
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=f"Could not retry hijack of agent '{name}': {exc}",
            exit_code=EXIT_FAILED,
            hijack_id=hijack_id or None,
            record=ledger.load_record(hijack_id) if hijack_id else active,
            reason="retry_failed",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=target.workspace_num,
        )
    termination = terminate_with_retry(target, deps=deps)
    if not termination.success:
        return build_stop_blocked_result(
            name,
            hijack_id,
            record,
            termination,
            subject=subject,
            target=target,
            decision=decision,
        )
    # Retry succeeded: fall through to the normal held settlement.
    return settle_held_result(
        name,
        target,
        hijack_id,
        record,
        deps=deps,
        subject=subject,
        decision=decision,
        pinned_by_us=False,
        record_snapshot_error=False,
        include_evidence_error=False,
    )


__all__ = [
    "retry_stop_blocked",
]

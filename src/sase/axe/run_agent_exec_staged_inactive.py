"""Idempotent settlement of never-started stages with failed origins.

One shared implementation serves the failed-dispatch boundary for new
failures and the bounded reconciler for historical stages. Settlement runs
only after re-observing the core inactive-stage policy's eligibility under
the adoption lock, converges on repeat runs, and preserves every recovery
record: the original stage, receipt, launch payload, response, and recovery
context all survive for explicit ``sase agent readopt``.

For an eligible never-started monitor, settlement reuses the held staged
cleanup: the owned reserved ToolRun settles as never executed, only the
stage's join/prepared reservation is released, and the stale pending-owner
index row is removed. An already-submitted proc is never stopped and its
prepared evidence is never discarded; unreadable proc state never enters
the absence branch because the policy reports it unknown and ineligible.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InactiveStageSettlement:
    """Outcome of one idempotent inactive-stage settlement attempt."""

    settled: bool
    already_settled: bool
    staged_id: str | None
    reason: str
    settled_tool_run_id: str | None = None
    released_join: bool = False
    released_prepared_intent: bool = False
    cleared_pending_owner: bool = False


def settle_inactive_staged_handoff(
    artifacts_dir: str, *, blocking: bool = True
) -> InactiveStageSettlement:
    """Settle one failed origin's never-started stage. Safe to repeat.

    Acquires the adoption lock, re-observes the core policy, and settles
    only when eligible. Returns without mutating anything otherwise. With
    ``blocking=False`` a busy lock skips the attempt instead of waiting:
    opportunistic callers (the bounded reconciler, the failed-dispatch
    path) must never stall another holder.
    """
    from sase.agent.staged_handoff import acquire_adoption_lock

    with acquire_adoption_lock(Path(str(artifacts_dir)), blocking=blocking) as acquired:
        if not acquired:
            return InactiveStageSettlement(
                settled=False,
                already_settled=False,
                staged_id=None,
                reason="another caller owns the staged adoption lock",
            )
        return _settle_inactive_staged_handoff_locked(str(artifacts_dir))


def maybe_settle_automatic_hold(
    artifacts_dir: str,
) -> InactiveStageSettlement | None:
    """Settle one automatic hold's failed origin. The caller holds the lock.

    Returns the settlement when the origin carries durable failed-terminal
    evidence, else ``None`` without touching anything. Read-only stranded
    collection never settles; this runs only on the terminal-origin
    boundary for new failures and the bounded reconciler's automatic pass
    for historical stages.
    """
    from sase.agent._staged_handoff_inactive import observe_inactive_stage_request

    try:
        request = observe_inactive_stage_request(str(artifacts_dir))
    except Exception:
        return None
    if request is None or request.get("origin_outcome") != "failed":
        return None
    return _settle_inactive_staged_handoff_locked(str(artifacts_dir))


def _settle_inactive_staged_handoff_locked(
    artifacts_dir: str,
) -> InactiveStageSettlement:
    """Settle one stage assuming the caller holds the adoption lock."""
    from sase.agent._staged_handoff_inactive import (
        INACTIVE_SETTLEMENT_SCHEMA_VERSION,
        observe_inactive_stage_request,
        settlement_matches_stage,
        write_inactive_settlement_locked,
    )
    from sase.agent._staged_handoff_store import now_rfc3339, read_staged_handoff
    from sase.core.staged_handoff import evaluate_inactive_staged_handoff

    origin = str(artifacts_dir)
    staged_record: Any = None
    try:
        staged_record = read_staged_handoff(origin)
    except Exception:
        staged_record = "malformed"
    if not isinstance(staged_record, dict):
        return InactiveStageSettlement(
            settled=False,
            already_settled=False,
            staged_id=None,
            reason="no adoptable staged record to settle",
        )
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return InactiveStageSettlement(
            settled=False,
            already_settled=False,
            staged_id=None,
            reason="staged record has no identity to settle",
        )
    request = observe_inactive_stage_request(origin)
    if request is None:
        return InactiveStageSettlement(
            settled=False,
            already_settled=False,
            staged_id=staged_id,
            reason="inactive-stage facts are unavailable",
        )
    try:
        decision = evaluate_inactive_staged_handoff(request)
    except Exception as exc:
        return InactiveStageSettlement(
            settled=False,
            already_settled=False,
            staged_id=staged_id,
            reason=f"inactive-stage policy is unavailable: {exc}",
        )
    if not bool(decision.get("inactive")) or not bool(
        decision.get("settlement_eligible")
    ):
        return InactiveStageSettlement(
            settled=False,
            already_settled=False,
            staged_id=staged_id,
            reason=str(decision.get("reason") or "stage is not eligible"),
        )
    if settlement_matches_stage(origin, staged_id):
        return InactiveStageSettlement(
            settled=True,
            already_settled=True,
            staged_id=staged_id,
            reason=str(decision.get("reason") or "already settled"),
        )
    resource_state = _settle_monitor_resources(origin, staged_record)
    write_inactive_settlement_locked(
        {
            "schema_version": INACTIVE_SETTLEMENT_SCHEMA_VERSION,
            "staged_id": staged_id,
            "reason": str(decision.get("reason") or "origin_failed"),
            "origin_id": request.get("origin_id"),
            "settled_at": now_rfc3339(),
        },
        artifacts_dir=origin,
    )
    return InactiveStageSettlement(
        settled=True,
        already_settled=False,
        staged_id=staged_id,
        reason=str(decision.get("reason") or "origin_failed"),
        settled_tool_run_id=resource_state.get("settled_tool_run_id"),
        released_join=resource_state.get("released_join", False),
        released_prepared_intent=resource_state.get("released_prepared_intent", False),
        cleared_pending_owner=resource_state.get("cleared_pending_owner", False),
    )


def _settle_monitor_resources(
    origin: str, staged_record: dict[str, Any]
) -> dict[str, Any]:
    """Settle never-started monitor resources, preserving evidence.

    Uses the held staged cleanup so the outer record and recovery evidence
    survive, then removes only the stale pending-owner index row. A
    submitted proc keeps its run and prepared evidence for the retry.
    """
    state: dict[str, Any] = {
        "settled_tool_run_id": None,
        "released_join": False,
        "released_prepared_intent": False,
        "cleared_pending_owner": False,
    }
    if staged_record.get("kind") != "monitor":
        return state
    payload = staged_record.get("payload")
    if not isinstance(payload, dict):
        return state
    monitor_id = payload.get("monitor_id")
    if not isinstance(monitor_id, str) or not monitor_id:
        return state
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return state
    try:
        from sase.monitor.start_stage_cleanup import cleanup_staged_monitor
        from sase.monitor.staged_owner import (
            clear_staged_owner_index,
            staged_monitor_member_artifacts_dir,
        )
    except Exception:
        return state
    try:
        member_dir = staged_monitor_member_artifacts_dir(monitor_id, staged_id, payload)
    except Exception:
        member_dir = None
    if isinstance(member_dir, str) and member_dir:
        try:
            result = cleanup_staged_monitor(member_dir, held=True)
        except Exception:
            result = None
        if result is not None:
            state["settled_tool_run_id"] = result.settled_tool_run_id
            state["released_join"] = bool(result.released_join)
            state["released_prepared_intent"] = bool(result.released_prepared_intent)
    try:
        clear_staged_owner_index(monitor_id)
        state["cleared_pending_owner"] = True
    except Exception:
        pass
    return state


__all__ = [
    "InactiveStageSettlement",
    "maybe_settle_automatic_hold",
    "settle_inactive_staged_handoff",
]

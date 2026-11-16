"""Shared result and settlement helpers for the hijack stop protocol."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sase.agent.hijack._stop_claim import terminate_tree
from sase.agent.hijack._stop_models import HijackTarget, StopDeps

LOG = logging.getLogger(__name__)

#: Source tag recorded in the user-kill intent marker.
STOP_INTENT_SOURCE = "agent_hijack"

EXIT_HELD = 0
EXIT_REFUSED = 2
EXIT_FAILED = 1
EXIT_LATCHED = 3

#: Bounded termination retries after the first attempt before custody
#: falls back to ``stop_blocked``. The verified terminator already
#: escalates SIGTERM to SIGKILL internally; the bound covers a second and
#: third pass for late-spawning children.
_STOP_RETRY_ATTEMPTS = 2


@dataclass
class HijackStopResult:
    """Outcome of one stop-orchestrator run."""

    status: str
    message: str
    exit_code: int
    hijack_id: str | None = None
    record: dict[str, Any] | None = None
    reason: str | None = None
    decision: dict[str, Any] | None = None
    occupant_name: str | None = None
    occupant_reason: str | None = None
    workspace_num: int | None = None


def terminate_with_retry(target: HijackTarget, *, deps: StopDeps) -> Any:
    """Run the verified terminator, retrying a bounded number of times.

    The terminator escalates SIGTERM to SIGKILL internally. A retry covers
    children that appeared while the tree shut down.
    """
    monitor_target = target.is_monitor_turn or target.monitor_id is not None
    if monitor_target:
        from sase.agent.hijack._stop_monitor import stop_monitor_target

        termination = stop_monitor_target(target, deps=deps)
    else:
        termination = terminate_tree(target, deps=deps)
    attempts = 0
    while (
        not termination.success
        and not getattr(termination, "identity_error", False)
        and attempts < _STOP_RETRY_ATTEMPTS
    ):
        attempts += 1
        LOG.warning(
            "hijack termination retry %d for %s: %s",
            attempts,
            target.name,
            getattr(termination, "error", None) or "survivors remain",
        )
        if monitor_target:
            from sase.agent.hijack._stop_monitor import stop_monitor_target

            termination = stop_monitor_target(target, deps=deps)
        else:
            termination = terminate_tree(target, deps=deps)
    return termination


def build_stop_blocked_result(
    name: str,
    hijack_id: str,
    record: dict[str, Any],
    termination: Any,
    *,
    subject: Any,
    target: HijackTarget,
    decision: dict[str, Any] | None = None,
) -> HijackStopResult:
    """Return the ``stop_blocked`` custody result for surviving writers."""
    from sase.agent.hijack import ledger

    survivors = [int(pid) for pid in (termination.survivors or ())]
    # Bounded retries are exhausted; retain custody in stop_blocked so
    # the workspace stays pinned and `,k` can retry. Only an explicit
    # abandon releases the claim.
    try:
        blocked = ledger.cas_advance_record(
            record,
            {
                "event": "stop_blocked",
                "error": termination.error or f"survivor pids: {survivors}",
            },
        )
        try:
            merged = ledger.merge_record_fields(hijack_id, {"survivor_pids": survivors})
            if isinstance(merged, dict):
                blocked = merged
        except Exception:
            pass
    except Exception:
        blocked = ledger.load_record(hijack_id) or record
    detail = f" ({len(survivors)} processes survived)" if survivors else ""
    return HijackStopResult(
        status="stop_blocked",
        message=(
            f"Could not fully stop agent '{name}'{detail}; workspace kept; "
            "`,k` retries, or release with x"
        ),
        exit_code=EXIT_FAILED,
        hijack_id=hijack_id,
        record=blocked,
        reason="stop_blocked",
        decision=decision,
        occupant_name=getattr(subject, "occupant_name", None),
        occupant_reason=getattr(subject, "occupant_reason", None),
        workspace_num=target.workspace_num,
    )


def settle_held_result(
    name: str,
    target: HijackTarget,
    hijack_id: str,
    record: dict[str, Any],
    *,
    deps: StopDeps,
    subject: Any,
    decision: dict[str, Any] | None = None,
    pinned_by_us: bool = False,
    record_snapshot_error: bool = True,
    include_evidence_error: bool = True,
) -> HijackStopResult:
    """Settle a stopped target into ``held`` and publish HIJACKED."""
    from sase.agent.hijack import ledger
    from sase.agent.hijack._stop_claim import ensure_hijacked_settlement
    from sase.agent.hijack._stop_evidence import (
        collect_and_attach_evidence,
        format_diff_summary,
    )

    ensure_hijacked_settlement(target, hijack_id, pinned_by_us)
    try:
        current = ledger.load_record(hijack_id) or record
    except Exception:
        current = record
    record_after_evidence, evidence_error, _snapshot_error = (
        collect_and_attach_evidence(
            hijack_id,
            target,
            deps=deps,
            record_snapshot_error=record_snapshot_error,
        )
    )
    current = record_after_evidence or ledger.load_record(hijack_id) or current
    try:
        held = ledger.cas_advance_record(current, {"event": "confirmed_stop"})
    except Exception as exc:
        return HijackStopResult(
            status="error",
            message=(
                f"Agent '{name}' was stopped but the hijack record could not "
                f"be published: {exc}"
            ),
            exit_code=EXIT_FAILED,
            hijack_id=hijack_id,
            record=ledger.load_record(hijack_id) or current,
            reason="publish_failed",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=target.workspace_num,
        )
    summary = format_diff_summary(held)
    held_suffix = f" · {summary}" if summary else ""
    if include_evidence_error and evidence_error:
        held_suffix += f" (snapshot pending: {evidence_error})"
    return HijackStopResult(
        status="held",
        message=(
            f"\u23cf hijacked {target.name} \u00b7 ws #{target.workspace_num} held"
            f"{held_suffix} \u00b7 next: sase agent recover {target.name}"
        ),
        exit_code=EXIT_HELD,
        hijack_id=hijack_id,
        record=held,
        decision=decision,
        occupant_name=getattr(subject, "occupant_name", None),
        occupant_reason=getattr(subject, "occupant_reason", None),
        workspace_num=target.workspace_num,
    )


__all__ = [
    "EXIT_FAILED",
    "EXIT_HELD",
    "EXIT_LATCHED",
    "EXIT_REFUSED",
    "HijackStopResult",
    "STOP_INTENT_SOURCE",
    "build_stop_blocked_result",
    "settle_held_result",
    "terminate_with_retry",
]

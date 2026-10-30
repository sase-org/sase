"""Pending gate turn settlement helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.config import get_gate_turn_reclaim_grace_seconds
from sase.gate_turn.lane_lock import try_gate_lane_lock
from sase.gate_turn.lifecycle import (
    DISPOSITION_ACCEPTED_FAILED,
    DISPOSITION_ACCEPTED_OWNER_LOST,
    DISPOSITION_ACCEPTED_UNFINISHED,
    DISPOSITION_ANSWERED,
    DISPOSITION_CANCELLED_LOST,
    DISPOSITION_CANCELLED_STOPPED,
    DISPOSITION_CANCELLED_TIMEOUT,
    DISPOSITION_EXPIRED_GRACE,
    DISPOSITION_EXPIRED_REVIEW,
    DISPOSITION_PENDING,
    classify_gate_lifecycle,
    collect_gate_lifecycle_facts,
    resolve_already_answered_race,
)
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn._reclaim_shared import MAX_ERROR_DETAILS
from sase.gate_turn.settlement import settle_gate_turn
from sase.gate_turn.store import (
    GateTurnSnapshot,
    list_gate_turns,
    read_gate_turn_marker,
)
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.failure_outcome import record_owner_lost_outcome_if_current
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class GateTurnReclaimSummary:
    """Summary of one reclaim pass."""

    scanned: int = 0
    answered: int = 0
    stopped: int = 0
    timed_out: int = 0
    lost: int = 0
    accepted_unfinished: int = 0
    accepted_failed: int = 0
    accepted_owner_lost: int = 0
    errors: int = 0
    error_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "answered": self.answered,
            "stopped": self.stopped,
            "timed_out": self.timed_out,
            "lost": self.lost,
            "accepted_unfinished": self.accepted_unfinished,
            "accepted_failed": self.accepted_failed,
            "accepted_owner_lost": self.accepted_owner_lost,
            "errors": self.errors,
        }


def reclaim_pending_gate_turns(
    *,
    now: float | None = None,
    grace_seconds: int | None = None,
    project: str | None = None,
    snapshot: GateTurnSnapshot | None = None,
) -> GateTurnReclaimSummary:
    """Settle pending gate turns that no longer have a live pending gate.

    A caller that already read the artifact index this pass (e.g. because it
    also runs :func:`reconcile_incomplete_gate_handoffs`) passes ``snapshot``
    so this phase does not read it again.
    """
    current = time.time() if now is None else now
    grace = (
        get_gate_turn_reclaim_grace_seconds()
        if grace_seconds is None
        else grace_seconds
    )
    counts = {
        "scanned": 0,
        "answered": 0,
        "stopped": 0,
        "timed_out": 0,
        "lost": 0,
        "accepted_unfinished": 0,
        "accepted_failed": 0,
        "accepted_owner_lost": 0,
        "errors": 0,
    }
    error_details: list[str] = []
    records = (
        snapshot.gate_turns
        if snapshot is not None
        else list_gate_turns(project=project)
    )
    for record in records:
        if record.is_terminal:
            continue
        counts["scanned"] += 1
        try:
            state = _reclaim_one(record, now=current, grace_seconds=grace)
        except Exception as error:
            counts["errors"] += 1
            if len(error_details) < MAX_ERROR_DETAILS:
                error_details.append(
                    f"{record.member_agent_name or record.gate_id}: "
                    f"{type(error).__name__}: {error}"
                )
            continue
        if state == "answered":
            counts["answered"] += 1
        elif state == "stopped":
            counts["stopped"] += 1
        elif state == "timeout":
            counts["timed_out"] += 1
        elif state == "lost":
            counts["lost"] += 1
        elif state == "accepted_unfinished":
            counts["accepted_unfinished"] += 1
        elif state == "accepted_failed":
            counts["accepted_failed"] += 1
        elif state == "accepted_owner_lost":
            counts["accepted_owner_lost"] += 1
    return GateTurnReclaimSummary(**counts, error_details=tuple(error_details))


def settle_lost_unless_creating(
    record: GateTurnRecord,
    reason: str,
) -> Literal["creating", "reachable", "settled"] | None:
    """Settle a bundle-less gate turn as lost unless its creation is running.

    The reclaim chop acts on a snapshot read seconds earlier, so a pending
    member with no bundle path may be mid-creation: its ``gate_bundle_path``
    is only recorded after ``create_gate()`` returns, while an ``%auto``
    gate still executes its selected commands inline. Settling such a
    member ``lost`` races the live creator's own settlement.

    Every creation runs inside the lane lock, so holding it here proves no
    creation is in flight: a ``False`` attempt means "creating", and the
    caller defers. Otherwise the member is re-read from disk (the snapshot
    may be stale) and, while still holding the lane lock, settled ``lost``
    with *reason* — ``settled`` — unless the fresh record is missing or
    already terminal (``None``: nothing to do) or now points at a
    verifiable bundle (``reachable``: the next pass classifies it normally).
    """
    with try_gate_lane_lock(record.project_name, record.lane) as acquired:
        if not acquired:
            return "creating"
        fresh = read_gate_turn_marker(record.project_name, record.artifacts_dir)
        if fresh is None or fresh.is_terminal:
            return None
        bundle = Path(fresh.bundle_path) if fresh.bundle_path else None
        if bundle is not None and bundle.is_dir():
            try:
                load_and_verify_bundle(bundle)
            except Exception:
                pass
            else:
                return "reachable"
        settle_gate_turn(fresh, gate_state="lost", reason=reason)
        return "settled"


def _reclaim_one(
    record: GateTurnRecord,
    *,
    now: float,
    grace_seconds: int,
) -> str | None:
    bundle = Path(record.bundle_path) if record.bundle_path else None
    if bundle is None or not bundle.is_dir():
        outcome = settle_lost_unless_creating(record, "gate bundle unreachable")
        return "lost" if outcome == "settled" else None
    try:
        envelope, _adapter = load_and_verify_bundle(bundle)
    except Exception:
        outcome = settle_lost_unless_creating(record, "gate bundle unreadable")
        return "lost" if outcome == "settled" else None

    deadline = _deadline(envelope)
    facts = collect_gate_lifecycle_facts(
        bundle, envelope, now=now, deadline=deadline, grace_seconds=grace_seconds
    )
    disposition = classify_gate_lifecycle(facts)["disposition"]

    if disposition == DISPOSITION_ANSWERED:
        settle_gate_turn(record, gate_state="answered", reason="gate answered")
        return "answered"
    if disposition == DISPOSITION_CANCELLED_TIMEOUT:
        settle_gate_turn(record, gate_state="timeout", reason="gate timed out")
        return "timeout"
    if disposition == DISPOSITION_CANCELLED_LOST:
        settle_gate_turn(record, gate_state="lost", reason="gate deadline grace passed")
        return "lost"
    if disposition == DISPOSITION_CANCELLED_STOPPED:
        settle_gate_turn(
            record,
            gate_state="stopped",
            reason=facts.cancellation_reason or "gate stopped",
        )
        return "stopped"
    if disposition == DISPOSITION_ACCEPTED_UNFINISHED:
        # The decision is durably accepted; execution may still be running.
        # Never cancel, settle as lost, or claim it completed here -- just
        # defer, so a concurrently completed response or accepted-but-stuck
        # execution stays visible for `sase gate show`/manual resume.
        return "accepted_unfinished"
    if disposition == DISPOSITION_ACCEPTED_FAILED:
        return "accepted_failed"
    if disposition == DISPOSITION_ACCEPTED_OWNER_LOST:
        failure = record_owner_lost_outcome_if_current(
            bundle,
            source="gate_turn_reclaim",
            now=now,
            deadline=deadline,
            grace_seconds=grace_seconds,
        )
        return "accepted_owner_lost" if failure is not None else "accepted_unfinished"
    if disposition == DISPOSITION_PENDING:
        return None
    if disposition == DISPOSITION_EXPIRED_REVIEW:
        return _settle_expired_gate(
            record,
            bundle,
            cancel_reason="timeout",
            settle_state="timeout",
            settle_reason="gate timed out",
        )
    if disposition == DISPOSITION_EXPIRED_GRACE:
        return _settle_expired_gate(
            record,
            bundle,
            cancel_reason="grace_expired",
            settle_state="lost",
            settle_reason="gate deadline grace passed",
        )
    raise RuntimeError(f"unrecognized gate lifecycle disposition {disposition!r}")


def _settle_expired_gate(
    record: GateTurnRecord,
    bundle: Path,
    *,
    cancel_reason: str,
    settle_state: Literal["timeout", "lost"],
    settle_reason: str,
) -> str:
    """Serialize an expiry decision with acceptance, then settle the shell.

    ``cancel_gate`` takes the gate's own ``.acceptance.lock`` and rereads
    fresh evidence before writing ``cancellation.json``, so acceptance
    cannot slip in between this pass's classification and the persisted
    outcome. A concurrent acceptance or completion is not a reclaim
    failure -- it is resolved from the same fresh evidence that made
    ``cancel_gate`` refuse.
    """
    try:
        cancel_gate(bundle, reason=cancel_reason, source="gate_turn_reclaim")
    except GateError as exc:
        if exc.code != "already_answered":
            raise
        disposition = resolve_already_answered_race(bundle, record.gate_id)
        if disposition == DISPOSITION_ANSWERED:
            settle_gate_turn(record, gate_state="answered", reason="gate answered")
            return "answered"
        return "accepted_unfinished"
    settle_gate_turn(record, gate_state=settle_state, reason=settle_reason)
    return settle_state


def _deadline(envelope: dict[str, Any]) -> float | None:
    created = envelope.get("created_at_unix")
    timeout_seconds = envelope.get("gate_timeout_seconds")
    if isinstance(created, (int, float)) and isinstance(timeout_seconds, (int, float)):
        return float(created) + float(timeout_seconds)
    return None


__all__ = [
    "GateTurnReclaimSummary",
    "reclaim_pending_gate_turns",
    "settle_lost_unless_creating",
]

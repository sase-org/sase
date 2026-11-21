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
from sase.gate_turn._lost_withdraw import withdraw_lost_gate
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
        if outcome == "settled":
            withdraw_lost_gate(record)
            return "lost"
        return None
    try:
        envelope, _adapter = load_and_verify_bundle(bundle)
    except Exception:
        outcome = settle_lost_unless_creating(record, "gate bundle unreadable")
        if outcome == "settled":
            withdraw_lost_gate(record)
            return "lost"
        return None

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
        withdraw_lost_gate(record)
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
        _backfill_member_failure(record, bundle, facts)
        _maybe_resurface_failure_notification(record, bundle, facts, now=now)
        return "accepted_failed"
    if disposition == DISPOSITION_ACCEPTED_OWNER_LOST:
        failure = record_owner_lost_outcome_if_current(
            bundle,
            source="gate_turn_reclaim",
            now=now,
            deadline=deadline,
            grace_seconds=grace_seconds,
        )
        if failure is None:
            return "accepted_unfinished"
        _backfill_member_failure(record, bundle, facts)
        _maybe_resurface_failure_notification(record, bundle, facts, now=now)
        return "accepted_owner_lost"
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
    if settle_state == "lost":
        withdraw_lost_gate(record)
    return settle_state


def _deadline(envelope: dict[str, Any]) -> float | None:
    created = envelope.get("created_at_unix")
    timeout_seconds = envelope.get("gate_timeout_seconds")
    if isinstance(created, (int, float)) and isinstance(timeout_seconds, (int, float)):
        return float(created) + float(timeout_seconds)
    return None


def _backfill_member_failure(record: GateTurnRecord, bundle: Path, facts: Any) -> None:
    """Persist the current journal failure onto an old-shape member.

    Gates that failed before ``gate_execution_failure`` existed have a
    durable ``attempt_failed`` journal event but no member meta object, so
    every surface still reads them as merely running. Backfilling keeps the
    member projection honest without reopening the bundle per row later.

    Serialized under the lane lock with a fresh re-read: a stale reclaim
    never overwrites a resumed owner, a resolved notification, or a newer
    failure for a different acceptance.
    """
    try:
        from sase.gate_turn.execution_failure import (
            build_gate_execution_failure,
            read_gate_execution_failure,
            write_gate_execution_failure,
        )
        from sase.gate_turn.lane_lock import try_gate_lane_lock
        from sase.gate_turn.store import read_gate_turn_marker
        from sase.notification_gates.failure_notifications import (
            gate_failure_action_data,
        )
        from sase.notification_gates.journal import current_gate_execution_failure

        with try_gate_lane_lock(record.project_name, record.lane) as acquired:
            if not acquired:
                return
            fresh = read_gate_turn_marker(record.project_name, record.artifacts_dir)
            if fresh is None or fresh.is_terminal:
                return
            existing = read_gate_execution_failure(fresh.artifacts_dir)
            receipt = facts.receipt if hasattr(facts, "receipt") else None
            receipt_acceptance = (
                receipt.get("acceptance_id") if isinstance(receipt, dict) else None
            )
            if isinstance(existing, dict):
                # Same acceptance already backfilled: nothing to do. A
                # different acceptance is a genuinely new failure and
                # replaces the stale object (history keeps the old allowance).
                if existing.get("acceptance_id") == receipt_acceptance:
                    return
            failure = current_gate_execution_failure(
                bundle, receipt, response_exists=False
            )
            if failure is None:
                return
            # Revalidate the journal failure is still current for this
            # acceptance before writing.
            if (
                isinstance(receipt_acceptance, str)
                and isinstance(failure.acceptance_id, str)
                and receipt_acceptance != failure.acceptance_id
            ):
                return
            try:
                envelope, _adapter = load_and_verify_bundle(bundle)
            except Exception:
                return
            # Do not backfill over a live settler claimed after our snapshot:
            # reclaim classifies outside the acceptance lock, so re-read the
            # member pid and skip when it names a new owner.
            fresh_after = read_gate_turn_marker(
                record.project_name, record.artifacts_dir
            )
            if fresh_after is None or fresh_after.is_terminal:
                return
            action_data = gate_failure_action_data(bundle, envelope, failure)
            error_report = str(action_data.get("error_report_path") or "")
            if not error_report and failure.error_record:
                error_report = str(bundle / failure.error_record)
            write_gate_execution_failure(
                fresh.artifacts_dir,
                build_gate_execution_failure(
                    stage=failure.stage,
                    code=failure.code,
                    message=failure.message,
                    error_record=failure.error_record,
                    error_report_path=error_report,
                    acceptance_id=failure.acceptance_id,
                    attempt_id=failure.attempt_id,
                    outcome_id=failure.outcome_id,
                    resume_command=str(action_data.get("resume_command") or ""),
                    restart_command=str(action_data.get("restart_command") or ""),
                    cancel_command=str(action_data.get("cancel_command") or ""),
                    recovery_actions=str(action_data.get("recovery_actions") or ""),
                    bundle_path=str(bundle),
                    request_id=str(envelope.get("request_id") or ""),
                    request_kind=str(envelope.get("kind") or ""),
                    at_unix=failure.at_unix,
                ),
            )
    except Exception:
        return


def _dismissal_age_seconds(
    notification: Any, *, artifacts_dir: str, now: float
) -> float | None:
    """Return seconds since *notification* was dismissed.

    Prefers the persisted dismissal timestamp when the store projects one;
    for legacy dismissed rows with no timestamp, records the first
    observation and waits a full hour from that observation. Never infers
    dismissal from failure time.
    """
    from sase.gate_turn.execution_failure import record_dismissal_observation

    dismissed_at = getattr(notification, "dismissed_at", None)
    if isinstance(dismissed_at, str) and dismissed_at:
        try:
            from datetime import UTC, datetime

            parsed = datetime.fromisoformat(dismissed_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, now - parsed.timestamp())
        except (ValueError, OSError, OverflowError):
            pass
    if isinstance(dismissed_at, (int, float)):
        try:
            return max(0.0, now - float(dismissed_at))
        except (ValueError, OSError, OverflowError):
            pass
    # Legacy row: first observation starts the hour.
    first_seen = record_dismissal_observation(artifacts_dir, notification.id, now=now)
    return max(0.0, now - float(first_seen))


def _core_resurface_eligible(
    *,
    dismissed_age_seconds: float,
    already_resurfaced: bool,
    already_visible: bool,
    receipt_matches: bool,
    is_terminal: bool,
) -> bool | None:
    """Ask the shared Rust policy whether resurface is eligible.

    Returns ``None`` when the binding is unavailable (stale core), so the
    caller falls back to the same Python checks. Python gathers facts;
    the core owns the decision.
    """
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("gate_failure_resurface_decision")
    except Exception:
        return None
    try:
        decision = binding(
            {
                "dismissed_age_seconds": float(dismissed_age_seconds),
                "already_resurfaced": bool(already_resurfaced),
                "already_visible": bool(already_visible),
                "receipt_matches": bool(receipt_matches),
                "is_terminal": bool(is_terminal),
            }
        )
        if isinstance(decision, dict):
            return bool(decision.get("eligible", False))
        return bool(getattr(decision, "eligible", False))
    except Exception:
        return None


def _maybe_resurface_failure_notification(
    record: GateTurnRecord, bundle: Path, facts: Any, *, now: float
) -> None:
    """Resurface a dismissed failure notification at most once per acceptance.

    For ``accepted_failed`` / ``accepted_owner_lost`` gates whose
    ``GateExecutionFailed`` notification was dismissed more than an hour ago
    and never resurfaced, restores it once through the store's
    un-dismiss path and records the resurface in the member meta.

    Identity first: request kind, gate ID and acceptance must match before
    another notification's dismissed/visible state is considered, so an
    unrelated visible failure never suppresses the target.
    """
    try:
        from sase.gate_turn.execution_failure import (
            gate_execution_failure_resurfaced,
            mark_gate_execution_failure_resurfaced,
            read_gate_execution_failure,
        )
        from sase.gate_turn.lane_lock import try_gate_lane_lock
        from sase.gate_turn.store import read_gate_turn_marker
        from sase.notification_gates.failure_notifications import (
            GATE_EXECUTION_FAILED_ACTION,
        )
        from sase.notifications.store import load_notifications

        with try_gate_lane_lock(record.project_name, record.lane) as acquired:
            if not acquired:
                return
            # Revalidate under the lock: a stale reclaim must not restore a
            # resolved notification or replace a newer acceptance.
            fresh = read_gate_turn_marker(record.project_name, record.artifacts_dir)
            if fresh is None or fresh.is_terminal:
                return
            failure_meta = read_gate_execution_failure(fresh.artifacts_dir)
            if not isinstance(failure_meta, dict):
                return
            acceptance_id = failure_meta.get("acceptance_id")
            if not isinstance(acceptance_id, str) or not acceptance_id:
                return
            if gate_execution_failure_resurfaced(
                fresh.artifacts_dir, acceptance_id=acceptance_id
            ):
                return
            receipt = facts.receipt if hasattr(facts, "receipt") else None
            receipt_acceptance = (
                receipt.get("acceptance_id") if isinstance(receipt, dict) else None
            )
            if receipt_acceptance != acceptance_id:
                return
            # Re-check the bundle still reports this acceptance as failed or
            # owner-lost; a concurrent resume/answer settles without us.
            try:
                from pathlib import Path as _Path

                response_exists = (_Path(bundle) / "response.json").exists()
                if response_exists:
                    return
            except OSError:
                return
            request_id = fresh.gate_id
            request_kind = (fresh.kind or "").strip()
            target = None
            target_visible = False
            for notification in load_notifications(include_dismissed=True):
                if notification.action != GATE_EXECUTION_FAILED_ACTION:
                    continue
                data = notification.action_data
                # Match identity before considering dismissed/visible state:
                # unrelated rows never suppress the target.
                if request_id and data.get("request_id") != request_id:
                    continue
                if request_kind and data.get("request_kind") not in ("", request_kind):
                    kind = data.get("request_kind")
                    if isinstance(kind, str) and kind and kind != request_kind:
                        continue
                if data.get("acceptance_id") != acceptance_id:
                    continue
                if not notification.dismissed:
                    target_visible = True
                    target = notification
                    break
                if target is None:
                    target = notification
            if target is None:
                return
            if target_visible or not target.dismissed:
                # Already visible: nothing to restore, and no resurface mark.
                return
            age = _dismissal_age_seconds(
                target, artifacts_dir=fresh.artifacts_dir, now=now
            )
            if age is None or age < 3600:
                return
            # Shared Rust policy owns the verdict; Python gathered the facts
            # above. Fall back to the same checks when the binding is stale.
            core_eligible = _core_resurface_eligible(
                dismissed_age_seconds=float(age),
                already_resurfaced=gate_execution_failure_resurfaced(
                    fresh.artifacts_dir, acceptance_id=acceptance_id
                ),
                already_visible=bool(target_visible),
                receipt_matches=(receipt_acceptance == acceptance_id),
                is_terminal=bool(fresh.is_terminal),
            )
            if core_eligible is not None:
                if not core_eligible:
                    return
            # Prove this invocation restored the row: matched alone is not
            # proof when the row is already visible. Only a changed write
            # earns the once-per-acceptance mark.
            from sase.notifications.store import restore_dismissed_notification

            if not restore_dismissed_notification(target.id):
                return
            mark_gate_execution_failure_resurfaced(
                fresh.artifacts_dir, acceptance_id=acceptance_id
            )
    except Exception:
        return


__all__ = [
    "GateTurnReclaimSummary",
    "reclaim_pending_gate_turns",
    "settle_lost_unless_creating",
]

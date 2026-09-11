"""Reclaim pending gate shells whose gates have already terminalized or expired."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config import get_gate_shell_reclaim_grace_seconds
from sase.gate_shell.handoff import (
    RECONCILE_BATCH_SIZE,
    apply_decision,
    classify_gate_handoff,
    collect_successor_evidence,
    load_reconcile_cursor,
    store_reconcile_cursor,
    with_gate_followup_lock,
)
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import list_gate_shells, read_gate_shell_marker
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.paths import CANCELLATION_FILENAME, RESPONSE_FILENAME


_MAX_ERROR_DETAILS = 5


@dataclass(frozen=True)
class GateShellReclaimSummary:
    """Summary of one reclaim pass."""

    scanned: int = 0
    answered: int = 0
    stopped: int = 0
    timed_out: int = 0
    lost: int = 0
    errors: int = 0
    error_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "answered": self.answered,
            "stopped": self.stopped,
            "timed_out": self.timed_out,
            "lost": self.lost,
            "errors": self.errors,
        }


def reclaim_pending_gate_shells(
    *,
    now: float | None = None,
    grace_seconds: int | None = None,
    project: str | None = None,
) -> GateShellReclaimSummary:
    """Settle pending gate shells that no longer have a live pending gate."""
    current = time.time() if now is None else now
    grace = (
        get_gate_shell_reclaim_grace_seconds()
        if grace_seconds is None
        else grace_seconds
    )
    counts = {
        "scanned": 0,
        "answered": 0,
        "stopped": 0,
        "timed_out": 0,
        "lost": 0,
        "errors": 0,
    }
    error_details: list[str] = []
    for record in list_gate_shells(project=project):
        if record.is_terminal:
            continue
        counts["scanned"] += 1
        try:
            state = _reclaim_one(record, now=current, grace_seconds=grace)
        except Exception as error:
            counts["errors"] += 1
            if len(error_details) < _MAX_ERROR_DETAILS:
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
    return GateShellReclaimSummary(**counts, error_details=tuple(error_details))


def _reclaim_one(
    record: GateShellRecord,
    *,
    now: float,
    grace_seconds: int,
) -> str | None:
    bundle = Path(record.bundle_path) if record.bundle_path else None
    if bundle is None or not bundle.is_dir():
        settle_gate_shell(record, gate_state="lost", reason="gate bundle unreachable")
        return "lost"
    try:
        envelope, _adapter = load_and_verify_bundle(bundle)
    except Exception:
        settle_gate_shell(record, gate_state="lost", reason="gate bundle unreadable")
        return "lost"

    response_path = bundle / RESPONSE_FILENAME
    if response_path.exists():
        settle_gate_shell(record, gate_state="answered", reason="gate answered")
        return "answered"
    cancellation_path = bundle / CANCELLATION_FILENAME
    if cancellation_path.exists():
        cancellation = _read_json(cancellation_path)
        reason = str(cancellation.get("reason") or "")
        if reason == "timeout":
            settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
            return "timeout"
        settle_gate_shell(record, gate_state="stopped", reason=reason or "gate stopped")
        return "stopped"

    deadline = _deadline(envelope)
    if deadline is None:
        return None
    if now >= deadline + grace_seconds:
        settle_gate_shell(
            record, gate_state="lost", reason="gate deadline grace passed"
        )
        return "lost"
    if now >= deadline:
        cancel_gate(bundle, reason="timeout", source="gate_shell_reclaim")
        settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
        return "timeout"
    return None


def _deadline(envelope: dict[str, Any]) -> float | None:
    created = envelope.get("created_at_unix")
    timeout_seconds = envelope.get("gate_timeout_seconds")
    if isinstance(created, (int, float)) and isinstance(timeout_seconds, (int, float)):
        return float(created) + float(timeout_seconds)
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except Exception:
        return {}


@dataclass(frozen=True)
class GateHandoffReconcileSummary:
    """Summary of one incomplete-handoff diagnosis pass."""

    scanned: int = 0
    incomplete: int = 0
    adopted: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, int]:
        return {
            "handoff_scanned": self.scanned,
            "handoff_incomplete": self.incomplete,
            "handoff_adopted": self.adopted,
            "handoff_skipped": self.skipped,
            "handoff_errors": self.errors,
        }


def reconcile_incomplete_gate_handoffs(
    *,
    project: str | None = None,
    batch_size: int = RECONCILE_BATCH_SIZE,
) -> GateHandoffReconcileSummary:
    """Diagnose terminal gates whose requested successor never recorded."""
    counts = {
        "scanned": 0,
        "incomplete": 0,
        "adopted": 0,
        "skipped": 0,
        "errors": 0,
    }
    error_details: list[str] = []
    records = [
        record for record in list_gate_shells(project=project) if record.is_terminal
    ]
    records.sort(key=lambda record: (record.timestamp, record.artifacts_dir))
    grouped: dict[str, list[Any]] = {}
    for record in records:
        grouped.setdefault(record.project_name, []).append(record)
    for project_name, project_records in grouped.items():
        _reconcile_project(
            project_name,
            project_records,
            batch_size=batch_size,
            counts=counts,
            error_details=error_details,
        )
    return GateHandoffReconcileSummary(**counts, error_details=tuple(error_details))


def _reconcile_project(
    project_name: str,
    records: list[Any],
    *,
    batch_size: int,
    counts: dict[str, int],
    error_details: list[str],
) -> None:
    cursor = load_reconcile_cursor(project_name)
    last_ts = str(cursor.get("timestamp") or "")
    last_dir = str(cursor.get("artifacts_dir") or "")
    remaining = batch_size
    last_seen: dict[str, str] | None = None
    for record in records:
        key = (record.timestamp, record.artifacts_dir)
        if last_ts and key <= (last_ts, last_dir):
            continue
        if remaining <= 0:
            break
        remaining -= 1
        counts["scanned"] += 1
        last_seen = {
            "timestamp": record.timestamp,
            "artifacts_dir": record.artifacts_dir,
        }
        try:
            outcome = _diagnose_one(record)
        except Exception as error:
            counts["errors"] += 1
            if len(error_details) < _MAX_ERROR_DETAILS:
                error_details.append(
                    f"{record.member_agent_name or record.gate_id}: "
                    f"{type(error).__name__}: {error}"
                )
            continue
        if outcome == "incomplete":
            counts["incomplete"] += 1
        elif outcome == "adopted":
            counts["adopted"] += 1
        else:
            counts["skipped"] += 1
    if last_seen is not None:
        store_reconcile_cursor(project_name, last_seen)


def _diagnose_one(record: Any) -> str:
    with with_gate_followup_lock(record.artifacts_dir):
        live = read_gate_shell_marker(record.project_name, record.artifacts_dir)
        if live is None:
            return "skipped"
        meta = {
            "gate_id": live.gate_id,
            "gate_kind": live.kind,
            "gate_state": live.gate_state,
            "gate_request_fingerprint": live.request_fingerprint,
            "name": live.member_agent_name,
            "agent_family": live.lane,
            "gate_followup_outcome": live.followup_outcome,
            "gate_followup_agent": live.followup_agent,
            "gate_followup_error": live.followup_error,
            "gate_followup_degraded_reason": live.followup_degraded_reason,
            "gate_followup_prompt_path": live.followup_prompt_path,
            "gate_followup_attempt_id": live.followup_attempt_id,
            "gate_followup_attempt_stage": live.followup_attempt_stage,
            "gate_followup_error_stage": live.followup_error_stage,
            "gate_followup_error_type": live.followup_error_type,
        }
        evidence = collect_successor_evidence(
            project_name=live.project_name,
            family=live.lane,
            expected_suffix=live.next_suffix,
            recorded_agent=live.followup_agent,
        )
        decision = classify_gate_handoff(
            meta,
            mode="diagnose",
            already_settled=True,
            followup_requested=bool(live.next_action),
            successor_evidence=evidence,
        )
        apply_decision(live.artifacts_dir, meta, decision)
        recovery = str(decision.get("recovery") or "")
        if recovery == "adopt":
            return "adopted"
        if decision.get("needs_attention"):
            return "incomplete"
        return "skipped"


__all__ = [
    "GateHandoffReconcileSummary",
    "GateShellReclaimSummary",
    "reclaim_pending_gate_shells",
    "reconcile_incomplete_gate_handoffs",
]

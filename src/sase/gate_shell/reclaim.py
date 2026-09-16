"""Reclaim pending gate shells whose gates have already terminalized or expired."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.config import get_gate_shell_reclaim_grace_seconds
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.gate_shell.handoff import (
    RECONCILE_BATCH_SIZE,
    apply_decision,
    classify_gate_handoff,
    collect_successor_evidence,
    load_reconcile_cursor,
    store_reconcile_cursor,
    with_gate_followup_lock,
)
from sase.gate_shell.lifecycle import (
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
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import (
    GateShellSnapshot,
    list_gate_shells,
    load_gate_shell_snapshot,
    read_gate_shell_marker,
)
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GateError


_MAX_ERROR_DETAILS = 5
#: Handoff reconciliation stops taking new gates after this long, well inside
#: the chop's two-minute timeout, so a slow pass still reports and resumes.
#: Only used when a caller does not pass an explicit ``deadline``.
_RECONCILE_TIME_BUDGET_SECONDS = 60.0
#: Filesystem mtimes can trail ``time.time()`` by a clock tick, so metadata
#: changed within this margin of a snapshot counts as changed after it.
_SNAPSHOT_MTIME_SLACK_SECONDS = 1.0
#: Conservative stand-in for a snapshot read's duration when the caller does
#: not measure and pass the real one, used to decide whether a mid-pass
#: refresh still leaves room before the deadline.
_DEFAULT_SNAPSHOT_READ_SECONDS = 7.0


@dataclass(frozen=True)
class GateShellReclaimSummary:
    """Summary of one reclaim pass."""

    scanned: int = 0
    answered: int = 0
    stopped: int = 0
    timed_out: int = 0
    lost: int = 0
    accepted_unfinished: int = 0
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
            "errors": self.errors,
        }


def reclaim_pending_gate_shells(
    *,
    now: float | None = None,
    grace_seconds: int | None = None,
    project: str | None = None,
    snapshot: GateShellSnapshot | None = None,
) -> GateShellReclaimSummary:
    """Settle pending gate shells that no longer have a live pending gate.

    A caller that already read the artifact index this pass (e.g. because it
    also runs :func:`reconcile_incomplete_gate_handoffs`) passes ``snapshot``
    so this phase does not read it again.
    """
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
        "accepted_unfinished": 0,
        "errors": 0,
    }
    error_details: list[str] = []
    records = (
        snapshot.gate_shells
        if snapshot is not None
        else list_gate_shells(project=project)
    )
    for record in records:
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
        elif state == "accepted_unfinished":
            counts["accepted_unfinished"] += 1
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

    deadline = _deadline(envelope)
    facts = collect_gate_lifecycle_facts(
        bundle, envelope, now=now, deadline=deadline, grace_seconds=grace_seconds
    )
    disposition = classify_gate_lifecycle(facts)["disposition"]

    if disposition == DISPOSITION_ANSWERED:
        settle_gate_shell(record, gate_state="answered", reason="gate answered")
        return "answered"
    if disposition == DISPOSITION_CANCELLED_TIMEOUT:
        settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
        return "timeout"
    if disposition == DISPOSITION_CANCELLED_LOST:
        settle_gate_shell(
            record, gate_state="lost", reason="gate deadline grace passed"
        )
        return "lost"
    if disposition == DISPOSITION_CANCELLED_STOPPED:
        settle_gate_shell(
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
    record: GateShellRecord,
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
        cancel_gate(bundle, reason=cancel_reason, source="gate_shell_reclaim")
    except GateError as exc:
        if exc.code != "already_answered":
            raise
        disposition = resolve_already_answered_race(bundle, record.gate_id)
        if disposition == DISPOSITION_ANSWERED:
            settle_gate_shell(record, gate_state="answered", reason="gate answered")
            return "answered"
        return "accepted_unfinished"
    settle_gate_shell(record, gate_state=settle_state, reason=settle_reason)
    return settle_state


def _deadline(envelope: dict[str, Any]) -> float | None:
    created = envelope.get("created_at_unix")
    timeout_seconds = envelope.get("gate_timeout_seconds")
    if isinstance(created, (int, float)) and isinstance(timeout_seconds, (int, float)):
        return float(created) + float(timeout_seconds)
    return None


@dataclass(frozen=True)
class GateHandoffReconcileSummary:
    """Summary of one incomplete-handoff diagnosis pass."""

    scanned: int = 0
    incomplete: int = 0
    adopted: int = 0
    skipped: int = 0
    errors: int = 0
    deferred: int = 0
    error_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, int]:
        return {
            "handoff_scanned": self.scanned,
            "handoff_incomplete": self.incomplete,
            "handoff_adopted": self.adopted,
            "handoff_skipped": self.skipped,
            "handoff_errors": self.errors,
            "handoff_deferred": self.deferred,
        }


@dataclass
class _ReconcilePassState:
    """Mutable snapshot state shared by every project and gate in one pass.

    At most one snapshot refresh happens per pass: the first gate whose
    metadata changed after ``snapshot`` was taken triggers it, and every
    later gate reuses the refreshed snapshot, or defers if it too changed
    after the refresh.
    """

    snapshot: GateShellSnapshot
    project: str | None
    read_seconds: float
    on_refresh: Callable[[str, float], None]
    refreshed: bool = False


def reconcile_incomplete_gate_handoffs(
    *,
    project: str | None = None,
    batch_size: int = RECONCILE_BATCH_SIZE,
    time_budget_seconds: float = _RECONCILE_TIME_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    snapshot: GateShellSnapshot | None = None,
    deadline: float | None = None,
    snapshot_read_seconds: float | None = None,
    on_refresh: Callable[[str, float], None] | None = None,
) -> GateHandoffReconcileSummary:
    """Diagnose terminal gates whose requested successor never recorded.

    A caller that already read the artifact index this pass passes
    ``snapshot`` (and, ideally, ``snapshot_read_seconds`` measured from that
    read) so this phase does not read it again. The pass saves each
    project's cursor after every gate, and defers the rest of its batches
    once ``deadline`` (or ``clock() + time_budget_seconds`` when no deadline
    is given) has passed.

    A gate whose metadata changed after the active snapshot triggers at most
    one snapshot refresh for the whole pass, as long as the refresh still
    leaves room before the deadline; a later changed gate is deferred
    instead of paying for another full index read.
    """
    pass_deadline = deadline if deadline is not None else clock() + time_budget_seconds
    counts = {
        "scanned": 0,
        "incomplete": 0,
        "adopted": 0,
        "skipped": 0,
        "errors": 0,
        "deferred": 0,
    }
    error_details: list[str] = []
    active_snapshot = (
        snapshot if snapshot is not None else load_gate_shell_snapshot(project=project)
    )
    pass_state = _ReconcilePassState(
        snapshot=active_snapshot,
        project=project,
        read_seconds=(
            _DEFAULT_SNAPSHOT_READ_SECONDS
            if snapshot_read_seconds is None
            else snapshot_read_seconds
        ),
        on_refresh=on_refresh or (lambda _gate, _seconds: None),
    )
    records = [
        record for record in pass_state.snapshot.gate_shells if record.is_terminal
    ]
    records.sort(key=lambda record: (record.timestamp, record.artifacts_dir))
    grouped: dict[str, list[GateShellRecord]] = {}
    for record in records:
        grouped.setdefault(record.project_name, []).append(record)
    for project_name, project_records in grouped.items():
        counts["deferred"] += _reconcile_project(
            project_name,
            project_records,
            pass_state=pass_state,
            batch_size=batch_size,
            deadline=pass_deadline,
            clock=clock,
            counts=counts,
            error_details=error_details,
        )
    return GateHandoffReconcileSummary(**counts, error_details=tuple(error_details))


def _reconcile_project(
    project_name: str,
    records: list[GateShellRecord],
    *,
    pass_state: _ReconcilePassState,
    batch_size: int,
    deadline: float,
    clock: Callable[[], float],
    counts: dict[str, int],
    error_details: list[str],
) -> int:
    """Diagnose one project's next batch; return how many gates were deferred."""
    cursor = load_reconcile_cursor(project_name)
    last_ts = str(cursor.get("timestamp") or "")
    last_dir = str(cursor.get("artifacts_dir") or "")
    batch = [
        record
        for record in records
        if not last_ts or (record.timestamp, record.artifacts_dir) > (last_ts, last_dir)
    ][:batch_size]
    for index, record in enumerate(batch):
        if clock() >= deadline:
            return len(batch) - index
        try:
            outcome = _diagnose_one(record, pass_state, deadline=deadline, clock=clock)
        except Exception as error:
            counts["scanned"] += 1
            counts["errors"] += 1
            if len(error_details) < _MAX_ERROR_DETAILS:
                error_details.append(
                    f"{record.member_agent_name or record.gate_id}: "
                    f"{type(error).__name__}: {error}"
                )
        else:
            if outcome is None:
                return len(batch) - index
            counts["scanned"] += 1
            if outcome == "incomplete":
                counts["incomplete"] += 1
            elif outcome == "adopted":
                counts["adopted"] += 1
            else:
                counts["skipped"] += 1
        store_reconcile_cursor(
            project_name,
            {"timestamp": record.timestamp, "artifacts_dir": record.artifacts_dir},
        )
    return 0


def _diagnose_one(
    record: GateShellRecord,
    pass_state: _ReconcilePassState,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> str | None:
    """Diagnose one settled gate, or return None if it must be deferred."""
    with with_gate_followup_lock(record.artifacts_dir):
        live = read_gate_shell_marker(record.project_name, record.artifacts_dir)
        if live is None:
            return "skipped"
        family_records = _resolve_family_records(
            pass_state, live, deadline=deadline, clock=clock
        )
        if family_records is None:
            return None
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
            family_records=family_records,
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


def _resolve_family_records(
    pass_state: _ReconcilePassState,
    live: GateShellRecord,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[AgentArtifactRecordWire, ...] | None:
    """Return live's family members from a fresh-enough snapshot, or None to defer.

    Launching or recording a successor rewrites the gate's metadata, so a
    gate touched after the active snapshot needs fresher evidence. The pass
    allows at most one refresh; a gate that still looks changed against the
    refreshed snapshot (or that finds no time left for a refresh) is
    deferred instead of falling back to a full per-gate index read.
    """
    if not _changed_since(live, pass_state.snapshot.taken_at):
        return pass_state.snapshot.family_records(live.project_name, live.lane)
    if pass_state.refreshed:
        return None
    if clock() + pass_state.read_seconds >= deadline:
        return None
    refresh_started = clock()
    pass_state.snapshot = load_gate_shell_snapshot(project=pass_state.project)
    pass_state.refreshed = True
    pass_state.on_refresh(
        live.member_agent_name or live.gate_id, clock() - refresh_started
    )
    if _changed_since(live, pass_state.snapshot.taken_at):
        return None
    return pass_state.snapshot.family_records(live.project_name, live.lane)


def _changed_since(live: GateShellRecord, taken_at: float) -> bool:
    """Return whether live's metadata was written at or after ``taken_at``."""
    meta_path = os.path.join(live.artifacts_dir, "agent_meta.json")
    try:
        changed_at = os.stat(meta_path).st_mtime
    except OSError:
        return True
    return changed_at + _SNAPSHOT_MTIME_SLACK_SECONDS >= taken_at


__all__ = [
    "GateHandoffReconcileSummary",
    "GateShellReclaimSummary",
    "reclaim_pending_gate_shells",
    "reconcile_incomplete_gate_handoffs",
]

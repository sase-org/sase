"""Incomplete gate handoff reconciliation and recovery."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.gate_turn.handoff import (
    ATTEMPT_ID_FIELD,
    ATTEMPT_STAGE_FIELD,
    ATTEMPT_STARTED_AT_FIELD,
    ERROR_TYPE_FIELD,
    RECONCILE_BATCH_SIZE,
    apply_decision,
    classify_gate_handoff,
    collect_successor_evidence,
    load_reconcile_cursor,
    notify_handoff_failure,
    store_reconcile_cursor,
    with_gate_followup_lock,
)
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn._reclaim_shared import MAX_ERROR_DETAILS
from sase.gate_turn.store import (
    GateTurnSnapshot,
    load_gate_turn_snapshot,
    read_gate_turn_marker,
)
from sase.ops.names import GATE_ANSWER
from sase.procs.request import ProcSubmitRequest
from sase.procs.submission import submit_proc_request


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
_INTERRUPTED_ATTEMPT_GRACE_SECONDS = 120.0


@dataclass(frozen=True)
class GateHandoffReconcileSummary:
    """Summary of one incomplete-handoff diagnosis pass."""

    scanned: int = 0
    incomplete: int = 0
    adopted: int = 0
    resumed: int = 0
    skipped: int = 0
    errors: int = 0
    deferred: int = 0
    error_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, int]:
        return {
            "handoff_scanned": self.scanned,
            "handoff_incomplete": self.incomplete,
            "handoff_adopted": self.adopted,
            "handoff_resumed": self.resumed,
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

    snapshot: GateTurnSnapshot
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
    snapshot: GateTurnSnapshot | None = None,
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
        "resumed": 0,
        "skipped": 0,
        "errors": 0,
        "deferred": 0,
    }
    error_details: list[str] = []
    active_snapshot = (
        snapshot if snapshot is not None else load_gate_turn_snapshot(project=project)
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
        record for record in pass_state.snapshot.gate_turns if record.is_terminal
    ]
    records.sort(key=lambda record: (record.timestamp, record.artifacts_dir))
    grouped: dict[str, list[GateTurnRecord]] = {}
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
    records: list[GateTurnRecord],
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
            if len(error_details) < MAX_ERROR_DETAILS:
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
            elif outcome == "resumed":
                counts["resumed"] += 1
            else:
                counts["skipped"] += 1
        store_reconcile_cursor(
            project_name,
            {"timestamp": record.timestamp, "artifacts_dir": record.artifacts_dir},
        )
    return 0


def _diagnose_one(
    record: GateTurnRecord,
    pass_state: _ReconcilePassState,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> str | None:
    """Diagnose one settled gate, or return None if it must be deferred."""
    with with_gate_followup_lock(record.artifacts_dir):
        live = read_gate_turn_marker(record.project_name, record.artifacts_dir)
        if live is None:
            return "skipped"
        agent_session_records = _resolve_agent_session_records(
            pass_state, live, deadline=deadline, clock=clock
        )
        if agent_session_records is None:
            return None
        meta = _read_reclaim_meta(live.artifacts_dir)
        meta.update(
            {
                key: value
                for key, value in {
                    "gate_id": live.gate_id,
                    "gate_kind": live.kind,
                    "gate_state": live.gate_state,
                    "gate_request_fingerprint": live.request_fingerprint,
                    "name": live.member_agent_name,
                    "agent_session": live.lane,
                    "gate_followup_outcome": live.followup_outcome,
                    "gate_followup_agent": live.followup_agent,
                    "gate_followup_error": live.followup_error,
                    "gate_followup_degraded_reason": live.followup_degraded_reason,
                    "gate_followup_prompt_path": live.followup_prompt_path,
                    "gate_followup_attempt_id": live.followup_attempt_id,
                    "gate_followup_attempt_stage": live.followup_attempt_stage,
                    "gate_followup_error_stage": live.followup_error_stage,
                    "gate_followup_error_type": live.followup_error_type,
                    "artifacts_dir": live.artifacts_dir,
                }.items()
                if value is not None
            }
        )
        evidence = collect_successor_evidence(
            project_name=live.project_name,
            agent_session=live.lane,
            expected_suffix=live.next_suffix,
            recorded_agent=live.followup_agent,
            gate_kind=live.kind,
            gate_timestamp=live.timestamp,
            exclude_agents={
                name for name in (live.creator_agent, live.member_agent_name) if name
            },
            agent_session_records=agent_session_records,
        )
        decision = classify_gate_handoff(
            meta,
            mode="diagnose",
            holds_followup_lock=True,
            already_settled=True,
            followup_requested=bool(live.next_action),
            successor_evidence=evidence,
        )
        if _is_interrupted_attempt(meta, decision, evidence):
            if _attempt_is_recent(meta, now=time.time()):
                return None
            attempt_id = meta.get(ATTEMPT_ID_FIELD)
            if (
                isinstance(attempt_id, str)
                and attempt_id
                and meta.get("gate_followup_auto_resume_attempt_id") != attempt_id
            ):
                try:
                    _auto_resume_interrupted_attempt(live, meta, attempt_id)
                except Exception:
                    # The durable attempt marker keeps this to one submission;
                    # notification below gives a human the explicit resume command.
                    pass
                else:
                    return "resumed"
        apply_decision(live.artifacts_dir, meta, decision)
        recovery = str(decision.get("recovery") or "")
        if recovery == "adopt":
            return "adopted"
        if decision.get("needs_attention"):
            attempt_id = meta.get(ATTEMPT_ID_FIELD)
            already_reported = bool(meta.get(ERROR_TYPE_FIELD)) or (
                isinstance(attempt_id, str)
                and meta.get("gate_followup_attention_notified_attempt_id")
                == attempt_id
            )
            if not already_reported:
                stage = meta.get(ATTEMPT_STAGE_FIELD)
                notify_handoff_failure(
                    meta,
                    error=str(decision.get("reason") or "follow-up needs attention"),
                    stage=(
                        stage if isinstance(stage, str) and stage else "interrupted"
                    ),
                )
                if isinstance(attempt_id, str) and attempt_id:
                    _persist_reclaim_meta(
                        live.artifacts_dir,
                        meta,
                        gate_followup_attention_notified_attempt_id=attempt_id,
                    )
            return "incomplete"
        return "skipped"


def _read_reclaim_meta(artifacts_dir: str) -> dict[str, Any]:
    """Load full gate metadata needed by reclaim decisions and notifications."""
    value = json.loads(
        (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    value["artifacts_dir"] = artifacts_dir
    return value


def _is_interrupted_attempt(
    meta: Mapping[str, Any],
    decision: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    """Return whether the classifier found an unambiguous interrupted launch."""
    return (
        meta.get(ATTEMPT_STAGE_FIELD) in {"preparing", "launching"}
        and not meta.get(ERROR_TYPE_FIELD)
        and decision.get("recovery") == "resume"
        and bool(decision.get("resume_eligible"))
        and not bool(evidence.get("ambiguous"))
        and not evidence.get("attached_agent")
        and not bool(evidence.get("running"))
        and not bool(evidence.get("completed"))
    )


def _attempt_is_recent(meta: dict[str, Any], *, now: float) -> bool:
    """Wait 120 seconds before recovering a launch that may still be indexing."""
    started_at = meta.get(ATTEMPT_STARTED_AT_FIELD)
    if not isinstance(started_at, str) or not started_at:
        return False
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return now - started.timestamp() < _INTERRUPTED_ATTEMPT_GRACE_SECONDS


def _auto_resume_interrupted_attempt(
    record: GateTurnRecord,
    meta: dict[str, Any],
    attempt_id: str,
) -> None:
    """Persist one resume marker and submit its gate answer as a supervised proc."""
    now = datetime.fromtimestamp(time.time(), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _persist_reclaim_meta(
        record.artifacts_dir,
        meta,
        gate_followup_auto_resume_attempt_id=attempt_id,
        gate_followup_auto_resume_at=now,
    )
    selected = meta.get("gate_selected_option_ids")
    if not isinstance(selected, list):
        raise ValueError("gate_selected_option_ids is missing or invalid")
    submit_proc_request(
        ProcSubmitRequest(
            argv=[
                "sase",
                "gate",
                "answer",
                "--id",
                record.gate_id,
                "--kind",
                record.kind,
                "--no-detach",
                "--json",
            ],
            label=f"Gate resume: {record.kind}/{record.gate_id}",
            cwd=str(Path.cwd()),
            origin="gate-turn-reclaim-resume",
            operation=GATE_ANSWER,
            operation_payload={
                "option_ids": selected,
                "retry": "resume",
                "source": "gate-reconcile",
            },
            project=record.project_name,
            cl_name=str(meta.get("cl_name") or "") or None,
        )
    )


def _persist_reclaim_meta(
    artifacts_dir: str,
    meta: dict[str, Any],
    **fields: Any,
) -> None:
    """Persist reclaim markers while preserving the full gate metadata object."""
    from sase.axe.agent_meta import write_agent_meta_atomic
    from sase.core.agent_artifact_index_lifecycle import (
        update_agent_artifact_index_for_marker_mutation,
    )

    meta.update(fields)
    payload = dict(meta)
    payload.pop("artifacts_dir", None)
    write_agent_meta_atomic(
        artifacts_dir,
        payload,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )


def _resolve_agent_session_records(
    pass_state: _ReconcilePassState,
    live: GateTurnRecord,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[AgentArtifactRecordWire, ...] | None:
    """Return live's agent-session members from a fresh-enough snapshot, or None to defer.

    Launching or recording a successor rewrites the gate's metadata, so a
    gate touched after the active snapshot needs fresher evidence. The pass
    allows at most one refresh; a gate that still looks changed against the
    refreshed snapshot (or that finds no time left for a refresh) is
    deferred instead of falling back to a full per-gate index read.
    """
    if not _changed_since(live, pass_state.snapshot.taken_at):
        return pass_state.snapshot.agent_session_records(live.project_name, live.lane)
    if pass_state.refreshed:
        return None
    if clock() + pass_state.read_seconds >= deadline:
        return None
    refresh_started = clock()
    pass_state.snapshot = load_gate_turn_snapshot(project=pass_state.project)
    pass_state.refreshed = True
    pass_state.on_refresh(
        live.member_agent_name or live.gate_id, clock() - refresh_started
    )
    if _changed_since(live, pass_state.snapshot.taken_at):
        return None
    return pass_state.snapshot.agent_session_records(live.project_name, live.lane)


def _changed_since(live: GateTurnRecord, taken_at: float) -> bool:
    """Return whether live's metadata was written at or after ``taken_at``."""
    meta_path = os.path.join(live.artifacts_dir, "agent_meta.json")
    try:
        changed_at = os.stat(meta_path).st_mtime
    except OSError:
        return True
    return changed_at + _SNAPSHOT_MTIME_SLACK_SECONDS >= taken_at


__all__ = [
    "GateHandoffReconcileSummary",
    "reconcile_incomplete_gate_handoffs",
]

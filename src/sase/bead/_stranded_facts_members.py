"""Per-member stranded-work facts: lifecycle, liveness, staged handoff."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sase.agent._running_listing_common import (
    active_status_for_record,
    is_monitor_member_meta,
    parse_iso_datetime,
    parse_started_at,
    record_is_live,
)
from sase.agent._running_listing_running import is_visible_monitor_record
from sase.agent.auto_restart.forward import recovery_in_flight
from sase.agent.handoff_inflight import HANDOFF_INFLIGHT_MARKER
from sase.agent.pending_handoff import pending_handoff_kind
from sase.agent.status_buckets import QUEUED_STATUS
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.runner_slots import is_real_gate_member_record
from sase.core.time import parse_local
from sase.core.wait_dependency_resolution._artifact_state import (
    turn_followup_handoff_agent,
    turn_followup_outcome,
)
from sase.core.wait_dependency_resolution._types import (
    SUCCESSFUL_TURN_FOLLOWUP_OUTCOMES,
)
from sase.workspace_provider.retention_record import read_workspace_retention_record

_FINALIZER_ACTIVE_PHASES = frozenset({"declaring", "executing"})
_PENDING_FOLLOWUP_AGENT = "<pending-turn-followup>"


def member_facts(record: AgentArtifactRecordWire) -> dict[str, Any]:
    """Build the reducer member dict for one artifact-index record."""
    meta = record.agent_meta
    name = ""
    if meta is not None and meta.name:
        name = meta.name
    elif record.done is not None and record.done.name:
        name = record.done.name
    turn_kind = _turn_kind(record)
    lifecycle = _lifecycle(record)
    process_live = _process_live(record)
    pending = pending_handoff_kind(record.artifact_dir)
    staged_kind, staged_outcome = _staged_facts(record.artifact_dir)
    staged_delivered = _staged_delivered(record.artifact_dir)
    followup_outcome, followup_pending, followup_agent, turn_state = _followup_fields(
        record
    )
    facts: dict[str, Any] = {
        "name": name,
        "artifact_dir": record.artifact_dir,
        "turn_kind": turn_kind,
        "lifecycle": lifecycle,
        "process_live": process_live,
        "remote": _is_remote(record),
        "finalizing": _is_finalizing(record),
        "pending_handoff": pending,
        "staged_handoff": staged_kind,
        "staged_receipt_outcome": staged_outcome,
        "staged_delivered": staged_delivered,
        "handoff_inflight": _handoff_inflight(record.artifact_dir),
        "recovery_in_flight": recovery_in_flight(record.artifact_dir),
        "workspace_retention": _workspace_retention_unresolved(record.artifact_dir),
        "turn_state": turn_state,
        "followup_pending": followup_pending,
        "followup_outcome": followup_outcome,
        "followup_agent": followup_agent,
        "declared_bead_action": None,
        "started_at": _started_at(record),
        "ended_at": _ended_at(record),
    }
    return facts


def epoch(value: str | int | float | None) -> float | None:
    """Parse a timestamp-like value to epoch seconds."""
    parsed = parse_local(value) if not isinstance(value, bool) else None
    if parsed is not None:
        return parsed.timestamp()
    if isinstance(value, str):
        started = parse_started_at(value)
        if started is not None:
            return started.timestamp()
    return None


def _staged_facts(artifact_dir: str) -> tuple[str | None, str | None]:
    """Return ``(staged_kind, staged_receipt_outcome)`` for stranded display.

    Malformed staged state reports ``"malformed"`` so the reducer never
    restarts or discards it as an ordinary abandoned run.
    """
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )
    except Exception:  # noqa: BLE001 - facts collection fails open.
        return None, None
    kind: str | None = None
    try:
        record = read_staged_handoff(artifact_dir)
        if record is not None:
            raw_kind = record.get("kind")
            kind = raw_kind if isinstance(raw_kind, str) and raw_kind else "plan"
    except StagedHandoffError:
        kind = "malformed"
    except Exception:  # noqa: BLE001 - facts collection fails open.
        kind = None
    outcome: str | None = None
    try:
        receipt = read_adoption_receipt(artifact_dir)
        if receipt is not None:
            raw_outcome = receipt.get("outcome")
            outcome = (
                raw_outcome if isinstance(raw_outcome, str) and raw_outcome else "held"
            )
    except StagedHandoffError:
        outcome = "malformed"
    except Exception:  # noqa: BLE001 - facts collection fails open.
        outcome = None
    return kind, outcome


def _staged_delivered(artifact_dir: str) -> bool:
    """Return whether a staged handoff is adopted and delivered.

    Mirrors ``_already_needs_delivery`` in the staged recovery service:
    non-successor kinds (``monitor``/``gate``) and successor kinds without
    a ``successor_artifacts_dir`` ref need only a matching ``adopted``
    receipt, while ``pipe``/``plan``/``questions`` stages with that ref
    need ``observe_destination`` to report ``owned`` or ``terminal``.
    Any read or contract error yields ``False``.
    """
    if not artifact_dir:
        return False
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_staged_handoff,
        )
        from sase.axe._run_agent_exec_staged_recovery_shared import (
            adopted_stage_needs_delivery,
            classify_receipt,
        )
        from sase.axe.run_agent_exec_staged_recovery_facts import (
            observe_destination,
        )
    except Exception:  # noqa: BLE001 - facts collection fails open.
        return False
    try:
        staged_record = read_staged_handoff(artifact_dir)
        if staged_record is None:
            return False
        staged_id = staged_record.get("staged_id")
        kind = staged_record.get("kind")
        if not isinstance(staged_id, str) or not staged_id:
            return False
        if not isinstance(kind, str) or not kind:
            return False
        receipt_state, receipt = classify_receipt(artifact_dir, staged_id)
        if receipt_state != "adopted":
            return False
        if not adopted_stage_needs_delivery(receipt, kind):
            return True
        return observe_destination(staged_record, artifacts_dir=artifact_dir) in (
            "owned",
            "terminal",
        )
    except StagedHandoffError:
        return False
    except Exception:  # noqa: BLE001 - facts collection fails open.
        return False


def _workspace_retention_unresolved(artifact_dir: str) -> bool:
    retention = read_workspace_retention_record(artifact_dir)
    return bool(retention is not None and retention.terminal and retention.unresolved)


def _turn_kind(record: AgentArtifactRecordWire) -> str:
    meta = record.agent_meta
    if meta is not None and meta.turn_kind in {"agent", "monitor", "gate"}:
        return meta.turn_kind
    turn = _session_turn(record)
    if turn is not None and turn.kind in {"monitor", "gate"}:
        return turn.kind
    if meta is not None and is_monitor_member_meta(meta):
        return "monitor"
    if is_real_gate_member_record(record):
        return "gate"
    return "agent"


def _session_turn(record: AgentArtifactRecordWire) -> Any:
    meta = record.agent_meta
    if meta is not None and meta.agent_session_turn is not None:
        return meta.agent_session_turn
    if record.done is not None:
        return record.done.agent_session_turn
    return None


def _lifecycle(record: AgentArtifactRecordWire) -> str:
    if record.has_done_marker:
        done = record.done
        if done is not None:
            if done.outcome == "hijacked" and _hijack_is_user_parked(done):
                return "asking"
            if done.outcome in {"failed", "epic_launch_failed"}:
                return "failed"
            if done.outcome == "stopped" or done.repeat_stopped:
                return "stopped"
        return "done"
    if record.waiting is not None:
        meta = record.agent_meta
        started = bool(meta is not None and meta.run_started_at)
        if record.waiting.slot_requested_at and not started:
            return "queued"
        return "waiting"
    status = active_status_for_record(record)
    if status == "QUESTION":
        return "asking"
    if status == "WAITING":
        return "waiting"
    if status == QUEUED_STATUS:
        return "queued"
    if status == "RUNNING":
        return "running"
    if status == "STARTING":
        return "starting"
    return "unknown"


def _hijack_is_user_parked(done: object) -> bool:
    from sase.agent.hijack.custody import recovery_is_user_parked

    recovery = getattr(done, "recovery", None)
    return recovery_is_user_parked(recovery)


def _process_live(record: AgentArtifactRecordWire) -> bool:
    if record.has_done_marker:
        done = record.done
        if (
            done is not None
            and done.outcome == "hijacked"
            and _hijack_is_user_parked(done)
        ):
            return True
        return False
    if record.waiting is not None:
        return True
    if record.pending_question is not None:
        return True
    if is_visible_monitor_record(record):
        return True
    if is_real_gate_member_record(record):
        turn = _session_turn(record)
        state = (getattr(turn, "state", None) or "").strip().lower()
        if state in {"running", "pending", "settling"}:
            return True
    return record_is_live(record)


def _is_remote(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    if meta is not None and (meta.source_machine or meta.imported_source_owner):
        return True
    done = record.done
    return bool(
        done is not None and (done.source_machine or done.imported_source_owner)
    )


def _is_finalizing(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    if meta is None:
        return False
    summary = meta.finalizer_status
    if summary is None:
        return False
    phase = (summary.phase or "").strip().lower()
    return phase in _FINALIZER_ACTIVE_PHASES


def _handoff_inflight(artifact_dir: str) -> bool:
    if not artifact_dir:
        return False
    try:
        return (Path(artifact_dir) / HANDOFF_INFLIGHT_MARKER).is_file()
    except OSError:
        return False


def _followup_fields(
    record: AgentArtifactRecordWire,
) -> tuple[str | None, bool, str | None, str | None]:
    turn = _session_turn(record)
    turn_state = None
    if turn is not None and isinstance(turn.state, str) and turn.state.strip():
        turn_state = turn.state.strip()
    meta_map, done_map = _meta_and_done_maps(record)
    outcome = turn_followup_outcome(meta_map, done_map)
    if outcome is None and turn is not None:
        raw = turn.followup_outcome
        if isinstance(raw, str) and raw.strip():
            outcome = raw.strip()
    followup_agent = turn_followup_handoff_agent(meta_map, done_map)
    pending = False
    agent: str | None = None
    if followup_agent == _PENDING_FOLLOWUP_AGENT:
        pending = True
    elif isinstance(followup_agent, str) and followup_agent.strip():
        agent = followup_agent.strip()
    if not pending and turn is not None:
        next_action = turn.next_action
        launched = outcome in SUCCESSFUL_TURN_FOLLOWUP_OUTCOMES if outcome else False
        if isinstance(next_action, str) and next_action.strip() and not launched:
            pending = True
    return outcome, pending, agent, turn_state


def _meta_and_done_maps(
    record: AgentArtifactRecordWire,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    meta = record.agent_meta
    meta_map = asdict(meta) if meta is not None else {}
    done_map = asdict(record.done) if record.done is not None else None
    return meta_map, done_map


def _started_at(record: AgentArtifactRecordWire) -> float | None:
    meta = record.agent_meta
    if meta is not None and meta.run_started_at:
        parsed = parse_iso_datetime(meta.run_started_at)
        if parsed is not None:
            return parsed.timestamp()
        started_epoch = epoch(meta.run_started_at)
        if started_epoch is not None:
            return started_epoch
    started = parse_started_at(record.timestamp)
    if started is not None:
        return started.timestamp()
    return epoch(record.timestamp)


def _ended_at(record: AgentArtifactRecordWire) -> float | None:
    done = record.done
    if done is None:
        return None
    if done.finished_at is not None:
        return float(done.finished_at)
    return None

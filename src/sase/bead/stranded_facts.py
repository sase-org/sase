"""Gather stranded-work facts for the sase-core reducer.

Python owns process liveness, marker files, and the small JSON reads the
host already performs. The scan is cheap (one index query per candidate
session, one JSON read per candidate) and ignores ACE dismissal so flags
survive hiding a row. Open beads that carry an active completion failure
are recovery candidates; their failure provenance names the run to load
without changing the bead assignee.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from collections.abc import Iterable
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
from sase.bead.completion_failure_codec import completion_failure_to_dict
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.bead_read_facade import list_issues
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import is_real_gate_member_record
from sase.core.stranded_work_facade import STRANDED_WORK_WIRE_SCHEMA_VERSION
from sase.core.time import parse_local
from sase.core.wait_dependency_resolution._artifact_state import (
    turn_followup_handoff_agent,
    turn_followup_outcome,
)
from sase.core.wait_dependency_resolution._types import (
    SUCCESSFUL_TURN_FOLLOWUP_OUTCOMES,
)
from sase.finalizers.declaration_manifest import (
    commit_bead_actions,
    load_latest_finalizer_submission,
)

_SETTLE_GRACE_SECONDS = 120.0
_FINALIZER_ACTIVE_PHASES = frozenset({"declaring", "executing"})
_PENDING_FOLLOWUP_AGENT = "<pending-turn-followup>"


def collect_stranded_work_input(
    project: str,
    *,
    now: float | None = None,
    bead_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build reducer input for *project*, optionally scoped to named beads."""
    moment = float(now) if now is not None else _now_epoch()
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return {
            "schema_version": STRANDED_WORK_WIRE_SCHEMA_VERSION,
            "now": moment,
            "settle_grace_seconds": _SETTLE_GRACE_SECONDS,
            "beads": [],
        }
    candidates, context = _candidate_and_context_issues(beads_dir, bead_ids=bead_ids)
    sessions = _session_record_cache(
        project,
        {key for issue in candidates for key in _session_keys_for_issue(issue)},
    )
    beads = [_bead_facts(issue, sessions, candidate=True) for issue in candidates]
    seen = {issue.id for issue in candidates}
    for issue in context:
        if issue.id in seen:
            continue
        seen.add(issue.id)
        beads.append(_bead_facts(issue, sessions, candidate=False))
    return {
        "schema_version": STRANDED_WORK_WIRE_SCHEMA_VERSION,
        "now": moment,
        "settle_grace_seconds": _SETTLE_GRACE_SECONDS,
        "beads": beads,
    }


def collect_issue_titles(
    project: str, *, bead_ids: Iterable[str] | None = None
) -> dict[str, str]:
    """Return bead-id to title for every issue the collector loaded."""
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return {}
    candidates, context = _candidate_and_context_issues(beads_dir, bead_ids=bead_ids)
    titles: dict[str, str] = {}
    for issue in (*candidates, *context):
        if issue.id and issue.id not in titles:
            titles[issue.id] = issue.title
    return titles


def _now_epoch() -> float:
    from time import time

    return time()


def _candidate_and_context_issues(
    beads_dir: Path, *, bead_ids: Iterable[str] | None = None
) -> tuple[list[Issue], list[Issue]]:
    loaded = list_issues(beads_dir, statuses=[Status.IN_PROGRESS, Status.OPEN])
    wanted = None if bead_ids is None else {item for item in bead_ids if item}
    candidates = [
        issue
        for issue in loaded
        if _is_stranded_candidate(issue) and (wanted is None or issue.id in wanted)
    ]
    phase_ids = {
        issue.id for issue in candidates if issue.issue_type is IssueType.PHASE
    }
    if not phase_ids:
        return candidates, []
    plans = list_issues(beads_dir, issue_types=[IssueType.PLAN])
    context = [
        issue
        for issue in plans
        if issue.parent_id in phase_ids and issue.id not in {c.id for c in candidates}
    ]
    return candidates, context


def _is_candidate(issue: Issue) -> bool:
    if issue.issue_type is IssueType.PHASE:
        return True
    if issue.issue_type is IssueType.TASK:
        return True
    return issue.issue_type is IssueType.PLAN and issue.tier is BeadTier.EPIC


def _is_stranded_candidate(issue: Issue) -> bool:
    if not _is_candidate(issue):
        return False
    if issue.status is Status.IN_PROGRESS:
        return True
    return issue.status is Status.OPEN and issue.completion_failure is not None


def _session_keys_for_issue(issue: Issue) -> tuple[str, ...]:
    keys: list[str] = []
    assignee = issue.assignee.strip()
    if assignee:
        keys.append(assignee)
    failure = issue.completion_failure
    if failure is not None:
        agent_name = failure.agent_name.strip()
        if agent_name and agent_name not in keys:
            keys.append(agent_name)
    return tuple(keys)


def _session_record_cache(
    project: str, assignees: set[str]
) -> dict[str, tuple[list[AgentArtifactRecordWire], bool]]:
    cache: dict[str, tuple[list[AgentArtifactRecordWire], bool]] = {}
    for assignee in sorted(assignees):
        cache[assignee] = _query_session_records(project, assignee)
    return cache


def _query_session_records(
    project: str, agent_session: str
) -> tuple[list[AgentArtifactRecordWire], bool]:
    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        return [], False
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        # A session's root member keeps agent_session null until it gets a
        # successor, so also match its agent_name; the recheck below keeps
        # the match exact.
        candidate_filter={
            "kind": "any",
            "filters": [
                {
                    "kind": "equals",
                    "field": "agent_session",
                    "value": agent_session,
                },
                {
                    "kind": "equals",
                    "field": "agent_name",
                    "value": agent_session,
                },
            ],
        },
    )
    options = AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project,),
    )
    try:
        scan = query_agent_artifact_index(
            index_path, sase_projects_dir(), query, options
        )
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
        return [], False
    records: list[AgentArtifactRecordWire] = []
    seen_dirs: set[str] = set()
    for record in scan.records:
        if record.artifact_dir in seen_dirs:
            continue
        if _record_matches_assignee(record, agent_session):
            seen_dirs.add(record.artifact_dir)
            records.append(record)
    return records, True


def _record_matches_assignee(record: AgentArtifactRecordWire, assignee: str) -> bool:
    meta = record.agent_meta
    if meta is None:
        return False
    session = (meta.agent_session or "").strip()
    name = (meta.name or "").strip()
    return session == assignee or name == assignee


def _bead_facts(
    issue: Issue,
    sessions: dict[str, tuple[list[AgentArtifactRecordWire], bool]],
    *,
    candidate: bool,
) -> dict[str, Any]:
    assignee = issue.assignee.strip() or None
    records_available = True
    records: list[AgentArtifactRecordWire] = []
    if candidate:
        records, records_available = _records_for_issue(issue, sessions)
    members = [_member_facts(record) for record in records] if candidate else []
    if candidate:
        _attach_declared_action(members)
    failure = issue.completion_failure
    return {
        "id": issue.id,
        "kind": _bead_kind(issue),
        "status": issue.status.value,
        "candidate": candidate,
        "assignee": assignee,
        "parent_id": issue.parent_id,
        "closed_at": _closed_at_epoch(issue),
        "records_available": records_available,
        "members": members,
        "completion_failure": (
            completion_failure_to_dict(failure) if failure is not None else None
        ),
    }


def _records_for_issue(
    issue: Issue,
    sessions: dict[str, tuple[list[AgentArtifactRecordWire], bool]],
) -> tuple[list[AgentArtifactRecordWire], bool]:
    keys = _session_keys_for_issue(issue)
    if not keys:
        return [], True
    merged: list[AgentArtifactRecordWire] = []
    seen_dirs: set[str] = set()
    available = False
    for key in keys:
        key_records, key_available = sessions.get(key, ([], False))
        available = available or key_available
        for record in key_records:
            artifact_dir = record.artifact_dir
            if artifact_dir in seen_dirs:
                continue
            seen_dirs.add(artifact_dir)
            merged.append(record)
    return merged, available


def _bead_kind(issue: Issue) -> str:
    if issue.issue_type is IssueType.TASK:
        return "task"
    if issue.issue_type is IssueType.PLAN:
        return "epic" if issue.tier is BeadTier.EPIC else "plan"
    return "phase"


def _closed_at_epoch(issue: Issue) -> float | None:
    return _epoch(issue.closed_at)


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


def _member_facts(record: AgentArtifactRecordWire) -> dict[str, Any]:
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
        # Staged fields ride the same reducer wire once the sase-core pin
        # includes them; omit when absent so the currently pinned core
        # (which denies unknown fields) still accepts ordinary members.
        "handoff_inflight": _handoff_inflight(record.artifact_dir),
        "recovery_in_flight": recovery_in_flight(record.artifact_dir),
        "turn_state": turn_state,
        "followup_pending": followup_pending,
        "followup_outcome": followup_outcome,
        "followup_agent": followup_agent,
        "declared_bead_action": None,
        "started_at": _started_at(record),
        "ended_at": _ended_at(record),
    }
    if staged_kind is not None:
        facts["staged_handoff"] = staged_kind
    if staged_outcome is not None:
        facts["staged_receipt_outcome"] = staged_outcome
    return facts


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


def _process_live(record: AgentArtifactRecordWire) -> bool:
    if record.has_done_marker:
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
        epoch = _epoch(meta.run_started_at)
        if epoch is not None:
            return epoch
    started = parse_started_at(record.timestamp)
    if started is not None:
        return started.timestamp()
    return _epoch(record.timestamp)


def _ended_at(record: AgentArtifactRecordWire) -> float | None:
    done = record.done
    if done is None:
        return None
    if done.finished_at is not None:
        return float(done.finished_at)
    return None


def _epoch(value: str | int | float | None) -> float | None:
    parsed = parse_local(value) if not isinstance(value, bool) else None
    if parsed is not None:
        return parsed.timestamp()
    if isinstance(value, str):
        started = parse_started_at(value)
        if started is not None:
            return started.timestamp()
    return None


def _attach_declared_action(members: list[dict[str, Any]]) -> None:
    newest: dict[str, Any] | None = None
    newest_key = float("-inf")
    for member in members:
        if member.get("turn_kind") != "agent":
            continue
        recency = member.get("ended_at")
        if recency is None:
            recency = member.get("started_at")
        key = float(recency) if isinstance(recency, (int, float)) else float("-inf")
        name = str(member.get("name") or "")
        newest_name = str(newest.get("name") or "") if newest else ""
        if key > newest_key or (key == newest_key and name > newest_name):
            newest = member
            newest_key = key
    if newest is None:
        return
    artifact_dir = newest.get("artifact_dir")
    if not isinstance(artifact_dir, str) or not artifact_dir:
        return
    newest["declared_bead_action"] = _declared_bead_action(artifact_dir)


def _declared_bead_action(artifact_dir: str) -> str | None:
    try:
        envelope = load_latest_finalizer_submission(Path(artifact_dir))
    except Exception:  # noqa: BLE001 - missing or malformed submission is unclosed.
        return None
    _has_commit, actions = commit_bead_actions(envelope)
    if "close" in actions:
        return "close"
    if "keep" in actions:
        return "keep"
    return None

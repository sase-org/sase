"""Per-bead stranded-work facts assembled from snapshot rows and members."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead._stranded_facts_members import epoch, member_facts
from sase.bead._stranded_facts_snapshot import session_record_cache
from sase.bead.completion_failure_codec import completion_failure_to_dict
from sase.bead.model import BeadTier, Issue, IssueType
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.stranded_work_facade import STRANDED_WORK_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration_manifest import (
    commit_bead_actions,
    load_latest_finalizer_submission,
)

_SETTLE_GRACE_SECONDS = 120.0


def empty_payload(moment: float) -> dict[str, Any]:
    """Return an empty reducer payload stamped at *moment*."""
    return {
        "schema_version": STRANDED_WORK_WIRE_SCHEMA_VERSION,
        "now": moment,
        "settle_grace_seconds": _SETTLE_GRACE_SECONDS,
        "beads": [],
    }


def payload_for_snapshot(
    project: str,
    moment: float,
    candidates: list[Issue],
    context: list[Issue],
) -> dict[str, Any]:
    """Build reducer input for one snapshot's candidate and context rows."""
    sessions = session_record_cache(
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


def titles_for_snapshot(
    candidates: list[Issue], context: list[Issue]
) -> dict[str, str]:
    """Return bead-id to title for every issue in the snapshot."""
    titles: dict[str, str] = {}
    for issue in (*candidates, *context):
        if issue.id and issue.id not in titles:
            titles[issue.id] = issue.title
    return titles


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
    members = [member_facts(record) for record in records] if candidate else []
    if candidate:
        attach_declared_bead_action(members)
    failure = issue.completion_failure
    return {
        "id": issue.id,
        "kind": _bead_kind(issue),
        "status": issue.status.value,
        "candidate": candidate,
        "assignee": assignee,
        "parent_id": issue.parent_id,
        "closed_at": epoch(issue.closed_at),
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


def attach_declared_bead_action(members: list[dict[str, Any]]) -> None:
    """Record the newest agent member's finalizer bead action, if any."""
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

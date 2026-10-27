"""Shared builders for stranded-work collector tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.bead import stranded_facts as facts
from sase.bead.model import BeadCompletionFailure, BeadTier, Issue, IssueType, Status
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    FinalizerStatusSummaryWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)

PROJECT = "demo"


def phase(
    bead_id: str,
    *,
    assignee: str = "",
    title: str = "Phase",
    status: Status = Status.IN_PROGRESS,
    parent_id: str | None = "sase-1",
    completion_failure: BeadCompletionFailure | None = None,
) -> Issue:
    return Issue(
        id=bead_id,
        title=title,
        status=status,
        issue_type=IssueType.PHASE,
        parent_id=parent_id,
        assignee=assignee,
        completion_failure=completion_failure,
    )


def epic(
    bead_id: str,
    *,
    assignee: str = "",
    title: str = "Epic",
    status: Status = Status.IN_PROGRESS,
    parent_id: str | None = None,
) -> Issue:
    return Issue(
        id=bead_id,
        title=title,
        status=status,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        parent_id=parent_id,
        assignee=assignee,
    )


def task(
    bead_id: str,
    *,
    assignee: str = "",
    title: str = "Task",
    status: Status = Status.IN_PROGRESS,
    completion_failure: BeadCompletionFailure | None = None,
) -> Issue:
    return Issue(
        id=bead_id,
        title=title,
        status=status,
        issue_type=IssueType.TASK,
        assignee=assignee,
        completion_failure=completion_failure,
    )


def child_plan(
    bead_id: str,
    *,
    parent_id: str,
    status: Status = Status.CLOSED,
    assignee: str = "",
    title: str = "Child plan",
    closed_at: str | None = None,
) -> Issue:
    return Issue(
        id=bead_id,
        title=title,
        status=status,
        issue_type=IssueType.PLAN,
        tier=BeadTier.PLAN,
        parent_id=parent_id,
        assignee=assignee,
        closed_at=closed_at,
    )


def write_submission(artifact_dir: Path, bead_action: str) -> None:
    payload = {
        "submission": {
            "payloads": [
                {
                    "payload": {
                        "repositories": [
                            {
                                "repo_id": "sase",
                                "action": "commit",
                                "message": "feat(scope): describe the completed work",
                                "bead_action": bead_action,
                            }
                        ]
                    }
                }
            ]
        }
    }
    (artifact_dir / "final_submission.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def record(
    artifact_dir: Path,
    *,
    name: str,
    session: str | None,
    timestamp: str = "20261022120000",
    pid: int | None = None,
    run_started_at: str | None = None,
    hidden: bool = False,
    source_machine: str | None = None,
    turn_kind: str = "agent",
    plan: bool = False,
    waiting: WaitingMarkerWire | None = None,
    pending_question: PendingQuestionMarkerWire | None = None,
    done: DoneMarkerWire | None = None,
    has_done_marker: bool | None = None,
    finalizer_phase: str | None = None,
    agent_session_turn: Any = None,
) -> AgentArtifactRecordWire:
    finalizer = None
    if finalizer_phase is not None:
        finalizer = FinalizerStatusSummaryWire(phase=finalizer_phase)
    done_present = has_done_marker if has_done_marker is not None else done is not None
    return AgentArtifactRecordWire(
        project_name=PROJECT,
        project_dir=f"/tmp/{PROJECT}",
        project_file=f"/tmp/{PROJECT}/{PROJECT}.sase",
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            agent_session=session,
            pid=pid,
            run_started_at=run_started_at,
            hidden=hidden,
            source_machine=source_machine,
            turn_kind=turn_kind,
            plan=plan,
            finalizer_status=finalizer,
            agent_session_turn=agent_session_turn,
        ),
        waiting=waiting,
        pending_question=pending_question,
        done=done,
        has_done_marker=done_present,
    )


def wire_collector(
    monkeypatch: Any,
    tmp_path: Path,
    issues: list[Issue],
    records: list[AgentArtifactRecordWire],
) -> Path:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir(exist_ok=True)
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_bytes(b"")
    monkeypatch.setattr(facts, "canonical_beads_dir_for_project", lambda _p: beads_dir)
    monkeypatch.setattr(facts, "default_agent_artifact_index_path", lambda: index)

    def list_issues(
        _beads_dir: Path,
        statuses: list[Status] | None = None,
        issue_types: list[IssueType] | None = None,
        tiers: list[BeadTier] | None = None,
    ) -> list[Issue]:
        result = list(issues)
        if statuses:
            result = [issue for issue in result if issue.status in statuses]
        if issue_types:
            result = [issue for issue in result if issue.issue_type in issue_types]
        if tiers:
            result = [issue for issue in result if issue.tier in tiers]
        return result

    monkeypatch.setattr(facts, "list_issues", list_issues)

    def query(
        _index_path: Path,
        projects_root: Path,
        _query: object,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        return AgentArtifactScanWire(
            schema_version=12,
            projects_root=str(projects_root),
            options=options or AgentArtifactScanOptionsWire(),
            stats=AgentArtifactScanStatsWire(),
            records=list(records),
        )

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    return beads_dir


def bead_facts(payload: dict[str, Any], bead_id: str) -> dict[str, Any]:
    return next(item for item in payload["beads"] if item["id"] == bead_id)

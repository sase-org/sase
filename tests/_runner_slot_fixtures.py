"""Shared artifact and scan-record fixtures for runner-slot tests."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)


def artifact(tmp_path: Path, name: str, pid: int, **extra_meta: object) -> Path:
    path = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / name
    path.mkdir(parents=True)
    (path / "agent_meta.json").write_text(json.dumps({"pid": pid, **extra_meta}))
    return path


def record(
    path: Path,
    *,
    started: bool = False,
    meta_wait_priority: int | None = None,
) -> AgentArtifactRecordWire:
    waiting_path = path / "waiting.json"
    waiting_data = (
        json.loads(waiting_path.read_text()) if waiting_path.exists() else None
    )
    meta = json.loads((path / "agent_meta.json").read_text())
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(path.parents[3]),
        project_file=str(path.parents[3] / "proj.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(path),
        timestamp=path.name,
        agent_meta=AgentMetaWire(
            pid=int(meta["pid"]),
            agent_family=meta.get("agent_family"),
            agent_family_role=meta.get("agent_family_role"),
            agent_family_parallel=bool(meta.get("agent_family_parallel", False)),
            parent_timestamp=meta.get("parent_timestamp"),
            monitor_id=meta.get("monitor_id"),
            wait_priority=meta_wait_priority,
            run_started_at=("2026-07-12T12:00:00+00:00" if started else None),
        ),
        waiting=(
            WaitingMarkerWire(
                waiting_for=list(waiting_data.get("waiting_for") or []),
                wait_runners=waiting_data.get("wait_runners"),
                wait_runners_explicit=bool(
                    waiting_data.get("wait_runners_explicit", False)
                ),
                wait_priority=waiting_data.get("wait_priority"),
                wait_priority_explicit=bool(
                    waiting_data.get("wait_priority_explicit", False)
                ),
                slot_requested_at=waiting_data.get("slot_requested_at"),
            )
            if waiting_data is not None
            else None
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=True),
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if (path / "pending_question.json").exists()
            else None
        ),
    )

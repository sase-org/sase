"""Shared builders for runner-slot admission tests."""

from __future__ import annotations

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    FamilyShellWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)


def _record(
    artifact_dir: str,
    *,
    project_name: str = "proj",
    pid: int = 100,
    run_started: bool = False,
    requested_at: str | None = None,
    wait_runners: int | None = None,
    wait_priority: int | None = None,
    meta_wait_priority: int | None = None,
    parent_timestamp: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    agent_family_parallel: bool = False,
    monitor_id: str | None = None,
    appears_as_agent: bool = True,
    done: bool = False,
    pending_question: bool = False,
    stopped_at: str | None = None,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=f"/projects/{project_name}",
        project_file=f"/projects/{project_name}/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=artifact_dir.rsplit("/", 1)[-1],
        agent_meta=AgentMetaWire(
            pid=pid,
            parent_timestamp=parent_timestamp,
            agent_family=agent_family,
            agent_family_role=agent_family_role,
            agent_family_parallel=agent_family_parallel,
            family_shell=(
                FamilyShellWire(kind="monitor", id=monitor_id)
                if monitor_id is not None
                else None
            ),
            wait_priority=meta_wait_priority,
            run_started_at=("2026-07-12T12:00:00+00:00" if run_started else None),
            stopped_at=stopped_at,
        ),
        waiting=(
            WaitingMarkerWire(
                wait_runners=wait_runners,
                wait_runners_explicit=wait_runners is not None,
                wait_priority=wait_priority,
                slot_requested_at=requested_at,
            )
            if requested_at is not None
            else None
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=appears_as_agent),
        has_done_marker=done,
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if pending_question
            else None
        ),
    )


def _always_live(_record: AgentArtifactRecordWire) -> bool:
    return True


def _live_unless_stopped(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    return meta is not None and meta.stopped_at is None

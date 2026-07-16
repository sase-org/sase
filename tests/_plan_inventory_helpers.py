"""Shared setup helpers for plan inventory tests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.core.paths import sase_projects_dir, sharded_path
from sase.core.time import get_timezone
from sase.notifications.models import Notification
from sase.notifications.store import append_notification
from tests._agent_loader_helpers import _empty_artifact_snapshot

LIVE_AGENT_TS = "20260613120000"
LIVE_AGENT_ROOT_TS = "20260613115900"


def timestamp(minutes_ago: int) -> datetime:
    return datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)


def touch(path: Path, value: datetime) -> None:
    epoch = value.timestamp()
    os.utime(path, (epoch, epoch))


def archived_plan(name: str, *, minutes_ago: int, title: str = "") -> Path:
    value = timestamp(minutes_ago)
    path = Path(sharded_path("plans", name, ts=value))
    canonical_title = title or path.stem.replace("_", " ").replace("-", " ").title()
    path.write_text(
        f"---\ntitle: {json.dumps(canonical_title)}\n---\n# {name}\n",
        encoding="utf-8",
    )
    touch(path, value)
    return path


def set_plan_tier(path: Path, tier: str) -> None:
    title = path.stem.replace("_", " ").replace("-", " ").title()
    path.write_text(
        f"---\ntitle: {json.dumps(title)}\ntier: {tier}\n---\n# {path.stem}\n",
        encoding="utf-8",
    )


def response_dir(root: Path, name: str) -> Path:
    path = root / "responses" / name
    path.mkdir(parents=True)
    (path / "plan_request.json").write_text("{}", encoding="utf-8")
    return path


def append_plan_notification(
    notification_id: str,
    plan_path: Path,
    response_path: Path,
    *,
    minutes_ago: int,
    agent_cl_name: str = "demo-cl",
    agent_name: str = "planner",
    agent_timestamp: str | None = LIVE_AGENT_TS,
    agent_root_timestamp: str | None = None,
    project_dir: str = "/work/demo-project",
) -> None:
    action_data = {
        "agent_name": agent_name,
        "llm_provider": "anthropic",
        "model": "claude-sonnet",
        "project_dir": project_dir,
        "response_dir": str(response_path),
    }
    if agent_cl_name:
        action_data["agent_cl_name"] = agent_cl_name
    if agent_timestamp:
        action_data["agent_timestamp"] = agent_timestamp
    if agent_root_timestamp:
        action_data["agent_root_timestamp"] = agent_root_timestamp
    append_notification(
        Notification(
            id=notification_id,
            timestamp=timestamp(minutes_ago).isoformat(),
            sender="plan",
            files=[str(plan_path)],
            action="PlanApproval",
            action_data=action_data,
        )
    )


def live_agent(
    *,
    status: str = "PLAN",
    cl_name: str = "demo-cl",
    agent_name: str = "planner",
    raw_suffix: str = LIVE_AGENT_TS,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/demo-project.sase",
        status=status,
        start_time=None,
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir="/work/demo-project",
    )


def write_agent_meta(
    project: str,
    workflow: str,
    raw_timestamp: str,
    data: dict[str, object],
    *,
    minutes_ago: int,
) -> Path:
    path = (
        sase_projects_dir()
        / project
        / "artifacts"
        / workflow
        / raw_timestamp
        / "agent_meta.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    touch(path, timestamp(minutes_ago))
    return path


def write_sharded_agent_meta(
    project: str,
    workflow: str,
    raw_timestamp: str,
    data: dict[str, object],
    *,
    minutes_ago: int,
) -> Path:
    artifact_dir = canonical_agent_artifact_path(
        project,
        workflow,
        raw_timestamp,
        projects_root=sase_projects_dir(),
    )
    artifact_dir.mkdir(parents=True)
    path = artifact_dir / "agent_meta.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    touch(path, timestamp(minutes_ago))
    return path


def done_plan_snapshot(
    *,
    project: str = "demo",
    timestamp: str = LIVE_AGENT_TS,
    cl_name: str = "demo-cl",
    agent_name: str = "planner",
) -> AgentArtifactScanWire:
    snapshot = _empty_artifact_snapshot()
    snapshot.records.append(
        AgentArtifactRecordWire(
            project_name=project,
            project_dir=f"/tmp/projects/{project}",
            project_file=f"/tmp/projects/{project}/{project}.sase",
            workflow_dir_name="ace-run",
            artifact_dir=f"/tmp/projects/{project}/artifacts/ace-run/{timestamp}",
            timestamp=timestamp,
            agent_meta=AgentMetaWire(
                name=agent_name,
                plan=True,
                plan_submitted_at=["2026-06-13T16:00:00Z"],
            ),
            done=DoneMarkerWire(
                outcome="completed",
                cl_name=cl_name,
                project_file=f"/tmp/projects/{project}/{project}.sase",
                name=agent_name,
            ),
            has_done_marker=True,
        )
    )
    return snapshot

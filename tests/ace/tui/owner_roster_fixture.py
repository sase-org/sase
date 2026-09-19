"""On-disk production fixture for owner-roster presentation parity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json
import os

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_facade import (
    rebuild_agent_artifact_index,
    replace_agent_artifact_index_dismissed_agents,
)


@dataclass(frozen=True)
class OwnerRosterFixture:
    """Hermetic SASE home with a modern family lifecycle on disk."""

    home: Path
    observations: dict[str, str]


def write_owner_roster_fixture(root: Path) -> OwnerRosterFixture:
    """Seed one shared on-disk lifecycle matching current persisted shape."""
    home = root / ".sase"
    projects = home / "projects"
    project = projects / "proj"
    artifacts = project / "artifacts" / "ace-run"
    artifacts.mkdir(parents=True)
    now = datetime.now()
    pid = os.getpid()

    def ts(minutes: int) -> str:
        return (now - timedelta(minutes=minutes)).strftime("%Y%m%d%H%M%S")

    root_ts = ts(20)
    plan_ts = ts(18)
    code_ts = ts(16)
    monitor_ts = ts(14)
    gate_ts = ts(12)
    proc_ts = ts(10)
    pending_gate_ts = ts(8)
    done_root_ts = ts(40)
    done_member_ts = ts(38)
    dismissed_ts = ts(6)
    recycled_ts = ts(4)
    fresh_ts = ts(2)
    _write_project(project, pid=pid, timestamp=fresh_ts)
    _write_alive(artifacts / root_ts, "lane", family="lane", role="root", pid=pid)
    _write_plan_shell(artifacts / plan_ts, "lane--plan", family="lane")
    _write_alive(
        artifacts / code_ts,
        "lane--code",
        family="lane",
        role="code",
        pid=pid,
    )
    _write_monitor(
        artifacts / monitor_ts,
        "lane--mon",
        family="lane",
        finished_at=(now - timedelta(minutes=14)).timestamp(),
    )
    _write_gate(
        artifacts / gate_ts,
        "lane--gate",
        family="lane",
        pending=False,
        finished_at=(now - timedelta(minutes=12)).timestamp(),
    )
    _write_proc(artifacts / proc_ts, "lane--proc", family="lane")
    _write_gate(
        artifacts / pending_gate_ts,
        "lane--gate-pending",
        family="lane",
        pending=True,
    )
    _write_done(
        artifacts / done_root_ts,
        "settled",
        family="settled",
        finished_at=(now - timedelta(minutes=40)).timestamp(),
    )
    _write_done(
        artifacts / done_member_ts,
        "settled--code",
        family="settled",
        finished_at=(now - timedelta(minutes=38)).timestamp(),
        parent=done_root_ts,
    )
    _write_dead(artifacts / dismissed_ts, "dismissed-old")
    _write_dead(artifacts / recycled_ts, "recycled")
    _write_alive(artifacts / fresh_ts, "fresh-launch", pid=pid)

    index = home / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index, projects)
    replace_agent_artifact_index_dismissed_agents(
        index,
        [
            AgentCleanupIdentityWire(
                agent_type="run",
                cl_name="unknown",
                raw_suffix=dismissed_ts,
            )
        ],
    )
    observations = {
        "lane": "alive",
        "lane--plan": "dead",
        "lane--code": "alive",
        "lane--mon": "dead",
        "lane--gate": "dead",
        "lane--proc": "dead",
        "lane--gate-pending": "dead",
        "settled": "dead",
        "settled--code": "dead",
        "dismissed-old": "alive",
        "recycled": "identity_mismatch",
        "fresh-launch": "alive",
    }
    return OwnerRosterFixture(home=home, observations=observations)


def _write_project(project: Path, *, pid: int, timestamp: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "proj.sase").write_text(
        "\n".join(
            [
                "NAME: proj",
                f"WORKSPACE_DIR: {project}",
                "PROJECT_STATE: enabled",
                "RUNNING:",
                f"  #1 | {pid} | ace(run)-fresh | proj | {timestamp} | PINNED",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_workflow_state(artifact: Path, name: str, *, pid: int, status: str) -> None:
    _write_json(
        artifact / "workflow_state.json",
        {
            "workflow_name": name,
            "status": status,
            "pid": pid,
            "appears_as_agent": True,
        },
    )


def _write_alive(
    artifact: Path,
    name: str,
    *,
    family: str | None = None,
    role: str | None = None,
    pid: int,
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": name}
    if family:
        meta["agent_family"] = family
    if role:
        meta["agent_family_role"] = role
    _write_json(artifact / "agent_meta.json", meta)
    _write_json(artifact / "running.json", {"pid": pid})
    _write_workflow_state(artifact, name, pid=pid, status="running")


def _write_dead(artifact: Path, name: str) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(artifact / "agent_meta.json", {"name": name})
    _write_json(artifact / "running.json", {"pid": 0})


def _write_plan_shell(artifact: Path, name: str, *, family: str) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "gate",
            "gate_id": "plan-gate",
            "gate_state": "pending",
        },
    )
    _write_json(artifact / "running.json", {"pid": 0})
    _write_workflow_state(artifact, name, pid=0, status="running")


def _write_monitor(
    artifact: Path, name: str, *, family: str, finished_at: float
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "monitor",
            "monitor_id": "mon-1",
            "monitor_state": "completed",
        },
    )
    _write_json(
        artifact / "done.json",
        {"outcome": "completed", "name": name, "finished_at": finished_at},
    )


def _write_gate(
    artifact: Path,
    name: str,
    *,
    family: str,
    pending: bool,
    finished_at: float | None = None,
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "agent_family_role": "gate",
            "gate_id": name,
            "gate_state": "pending" if pending else "completed",
        },
    )
    if pending:
        _write_json(artifact / "running.json", {"pid": 0})
        _write_json(artifact / "pending_question.json", {})
        _write_workflow_state(artifact, name, pid=0, status="waiting")
    else:
        _write_json(
            artifact / "done.json",
            {
                "outcome": "completed",
                "name": name,
                "finished_at": finished_at or 1.0,
            },
        )


def _write_proc(artifact: Path, name: str, *, family: str) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact / "agent_meta.json",
        {
            "name": name,
            "agent_family": family,
            "proc_id": "proc-1",
        },
    )
    _write_json(
        artifact / "done.json",
        {
            "outcome": "completed",
            "name": name,
            "finished_at": datetime.now().timestamp(),
        },
    )


def _write_done(
    artifact: Path,
    name: str,
    *,
    family: str,
    finished_at: float,
    parent: str | None = None,
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": name, "agent_family": family}
    if parent:
        meta["parent_timestamp"] = parent
    _write_json(artifact / "agent_meta.json", meta)
    _write_json(
        artifact / "done.json",
        {
            "outcome": "completed",
            "name": name,
            "finished_at": finished_at,
        },
    )

"""Capacity regressions through disk-backed monitor roster loading paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models import agent_loader
from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    root = tmp_path / ".sase" / "projects"
    project = root / "demo"
    project.mkdir(parents=True)
    (project / "demo.sase").write_text("PROJECT_NAME: demo\n")
    monkeypatch.setattr(agent_loader, "get_all_project_files", lambda: [])
    monkeypatch.setattr(agent_loader, "is_process_running", lambda pid: pid != 99999)
    monkeypatch.setattr(
        "sase.ace.hooks.processes.is_process_running", lambda pid: pid != 99999
    )
    for module in ("_workflow_loaders", "_workflow_snapshot_loaders"):
        monkeypatch.setattr(
            f"sase.ace.tui.models._loaders.{module}.is_process_running",
            lambda pid: pid != 99999,
        )
    monkeypatch.setattr("sase.ace.agent_tribes.load_agent_tribes", lambda: {})
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_token", lambda pid: "boot:100"
    )
    return root


def _artifact(
    projects: Path,
    index: int = 0,
    *,
    weight: float = 1.0,
    kind: str = "monitor",
    meta_pid: int | None = 12345,
    running_pid: int | None = None,
    state: str = "running",
    identity: str | None = None,
    owner: str | None = None,
    session: str | None = None,
) -> Path:
    timestamp = f"2026102600{index:02d}00"
    directory = projects / "demo" / "artifacts" / "ace-run" / timestamp
    directory.mkdir(parents=True)
    name = f"agent-{index}"
    meta: dict[str, object] = {
        "name": name,
        "pid": meta_pid,
        "process_identity": identity if kind != "monitor" else None,
        "queue_weight": weight,
        "queue_weight_explicit": True,
        "runner_claim_owner_key": owner,
        "agent_session": session,
    }
    if kind in {"monitor", "gate"}:
        meta.update(
            agent_session_role=kind,
            **{
                f"{kind}_id": f"turn-{index}",
                f"{kind}_state": state,
                f"{kind}_start_status": "TESTING" if kind == "monitor" else "WAITING",
                f"{kind}_stop_status": "TESTED",
            },
        )
    if kind == "monitor":
        meta["monitor_supervisor_identity"] = identity
    else:
        meta["run_started_at"] = "2026-10-26T00:00:00Z"
    (directory / "agent_meta.json").write_text(json.dumps(meta))
    (directory / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "ace(run)",
                "cl_name": name,
                "status": "running",
                "pid": meta_pid if kind != "monitor" else None,
                "appears_as_agent": True,
                "steps": [],
            }
        )
    )
    if running_pid is not None:
        (directory / "running.json").write_text(
            json.dumps(
                {"pid": running_pid, "cl_name": name, "process_identity": identity}
            )
        )
    return directory


def _load(projects: Path, dirs: list[Path], path: str) -> list[Agent]:
    if path == "delta":
        agents, state = agent_loader.load_artifact_delta_agents(
            dirs, patch_snapshot=[], update_index=False
        )
        assert not state.repair_recommended
        return agents
    if path == "filesystem":
        return load_workflow_agents(
            timestamp_dirs=[(projects / "demo", directory) for directory in dirs]
        )
    if path == "full":
        return agent_loader.load_all_agents(patch_snapshot=[])
    index_path = default_agent_artifact_index_path(projects.parent)
    rebuild_agent_artifact_index(index_path, projects)
    agents, state = agent_loader.load_tiered_agents(
        patch_snapshot=[], requested_limit=10 if path == "viewport" else None
    )
    assert state.used_artifact_index
    if path == "viewport":
        assert state.bounded_prefix
    return agents


@pytest.mark.parametrize("path", ["full", "index", "viewport", "delta", "filesystem"])
@pytest.mark.parametrize("weight", [1.0, 0.0])
@pytest.mark.parametrize("fallback", [False, True], ids=["metadata", "running-marker"])
def test_monitor_pid_and_weight_survive_loaders(
    projects: Path, path: str, weight: float, fallback: bool
) -> None:
    directory = _artifact(
        projects,
        weight=weight,
        meta_pid=None if fallback else 12345,
        running_pid=12345 if fallback else None,
    )
    agents = _load(projects, [directory], path)
    assert len(agents) == 1
    monitor = agents[0]
    assert monitor.pid == 12345
    assert monitor.is_monitor
    assert monitor.monitor_id == "turn-0"
    assert monitor.status == "TESTING"
    assert monitor.pid_liveness_unverified
    capacity = refresh_runner_slot_context(agents, effective_limit=8)
    assert capacity.occupied_capacity == weight
    assert [
        (holder.label, holder.weight, holder.kind) for holder in capacity.holders
    ] == [("agent-0", weight, "monitor")]


@pytest.mark.parametrize("path", ["full", "index", "viewport", "delta"])
@pytest.mark.parametrize("excluded", ["dead", "reused", "pending_gate", "terminal"])
def test_inactive_turns_never_become_capacity_claims(
    projects: Path, path: str, excluded: str
) -> None:
    directory = _artifact(
        projects,
        meta_pid=99999 if excluded == "dead" else 12345,
        identity="boot:99" if excluded == "reused" else "boot:100",
        kind="gate" if excluded == "pending_gate" else "monitor",
        state="pending" if excluded == "pending_gate" else "running",
    )
    if excluded == "terminal":
        (directory / "done.json").write_text(json.dumps({"outcome": "monitored"}))
    agents = _load(projects, [directory], path)
    assert agents
    capacity = refresh_runner_slot_context(agents, effective_limit=8)
    assert capacity.occupied_capacity == 0
    assert capacity.holders == ()
    if excluded in {"dead", "reused"}:
        assert not any(agent.runner_is_live for agent in agents)


def test_delta_spliced_into_full_roster_preserves_five_units(projects: Path) -> None:
    workers = [
        _artifact(projects, i, kind="worker", meta_pid=20000 + i) for i in range(3)
    ]
    monitors = [_artifact(projects, i, meta_pid=20000 + i) for i in range(3, 5)]
    monitors.append(_artifact(projects, 5, meta_pid=20005, weight=0))
    full = _load(projects, workers + monitors, "full")
    delta = _load(projects, monitors, "delta")
    changed = {str(directory) for directory in monitors}
    merged = [agent for agent in full if agent.artifacts_dir not in changed] + delta
    assert len(merged) == 6
    capacity = refresh_runner_slot_context(merged, effective_limit=8)
    assert capacity.occupied_capacity == 5
    assert len(capacity.holders) == 6
    assert sum(holder.weight == 0 for holder in capacity.holders) == 1


@pytest.mark.parametrize("same_owner", [False, True], ids=["parallel", "serial"])
def test_claim_owners_survive_roster_projection(
    projects: Path, same_owner: bool
) -> None:
    dirs = [
        _artifact(projects, 0, kind="worker", owner="branch-a", session="shared"),
        _artifact(
            projects,
            1,
            kind="worker",
            meta_pid=12346,
            owner="branch-a" if same_owner else "branch-b",
            session="shared",
        ),
    ]
    agents = _load(projects, dirs, "delta")
    assert {agent.runner_claim_owner_key for agent in agents} == (
        {"branch-a"} if same_owner else {"branch-a", "branch-b"}
    )
    capacity = refresh_runner_slot_context(agents, effective_limit=8)
    assert capacity.occupied_capacity == (1 if same_owner else 2)
    assert len(capacity.holders) == (1 if same_owner else 2)


def test_monitor_running_claim_merges_without_losing_projected_fields(
    projects: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.running_field import WorkspaceClaim

    directory = _artifact(projects, owner="monitor-claim", identity="boot:100")
    project_file = projects / "demo" / "demo.sase"
    monkeypatch.setattr(
        agent_loader, "get_all_project_files", lambda: [str(project_file)]
    )
    claim = WorkspaceClaim(
        workspace_num=7,
        pid=12345,
        workflow="ace-monitor",
        cl_name="agent-0",
        artifacts_timestamp=directory.name,
    )
    project_file.write_text("PROJECT_NAME: demo\nRUNNING:\n" + claim.to_line() + "\n")
    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._running_loaders.is_process_running",
        lambda _: True,
    )
    agents = _load(projects, [directory], "full")
    assert len(agents) == 1
    monitor = agents[0]
    assert monitor.pid == 12345
    assert monitor.workspace_num == 7
    assert monitor.runner_claim_owner_key == "monitor-claim"
    assert monitor.process_identity == "boot:100"
    assert monitor.monitor_id == "turn-0"
    assert monitor.status == "TESTING"
    assert refresh_runner_slot_context(agents, effective_limit=8).occupied_capacity == 1


@pytest.mark.parametrize("path", ["full", "index", "viewport", "delta", "filesystem"])
def test_monitor_metadata_pid_takes_precedence(projects: Path, path: str) -> None:
    directory = _artifact(projects, meta_pid=12345, running_pid=54321)
    agents = _load(projects, [directory], path)
    assert len(agents) == 1
    assert agents[0].pid == 12345

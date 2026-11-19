"""Parity tests: compact workflow constructors vs full snapshot loaders.

Each scenario writes real marker JSON into a scratch artifact directory,
builds the oracle rows through the real filesystem scan plus the existing
full snapshot loaders, and builds the candidate rows from the real Rust
compact list projection of the same tree through the new compact
workflow constructors. Every list/filter/action fact must match; only
explicitly deferred detail fields may differ.

Selected-record hydration (``_projected_record``) must then converge the
compact rows back to the deferred detail the full rows carry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.ace.tui.models._loaders._compact_workflow_loaders import (
    is_compact_workflow_state_record,
    load_compact_workflow_agent_steps_from_snapshot,
    load_compact_workflow_agents_from_snapshot,
)
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agent_steps_from_snapshot,
    load_workflow_agents_from_snapshot,
)
from sase.ace.tui.models._projected_record import hydrate_projected_agent
from sase.core.agent_scan_facade import (
    scan_agent_artifact_dirs,
    scan_agent_artifact_dirs_list,
)
from tests._agent_compact_parity_helpers import _assert_parity
from tests._agent_compact_parity_helpers import _facts


def _write_markers(artifact_dir: Path, markers: dict[str, Any]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in markers.items():
        (artifact_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _layout(tmp_path: Path, project: str, workflow: str, ts: str) -> Path:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / project / "artifacts" / workflow / ts
    return artifact_dir


def _snapshots(projects_root: Path, artifact_dir: Path):
    full = scan_agent_artifact_dirs(projects_root, [artifact_dir])
    assert len(full.records) == 1
    compact = scan_agent_artifact_dirs_list(projects_root, [artifact_dir])
    assert len(compact.records) == 1
    assert compact.records[0].record_shape == "compact"
    return full, compact


def _parent_by_cl(agents: list[Any], cl_name: str) -> Any:
    matches = [a for a in agents if a.cl_name == cl_name and not a.is_workflow_child]
    assert len(matches) == 1, cl_name
    return matches[0]


def test_workflow_parent_parity(tmp_path: Path) -> None:
    ts = "20261117130000"
    artifact_dir = _layout(tmp_path, "myproj", "workflow-deploy", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {
                "name": "deploy-agent",
                "cl_name": "cl-deploy",
                "model": "gpt-5.6-sol",
            },
            "workflow_state.json": {
                "workflow_name": "deploy",
                "status": "running",
                "pid": 999999999,
                "current_step_index": 1,
                "appears_as_agent": True,
                "is_anonymous": False,
                "hidden": False,
                "activity": "deploying",
                "steps": [
                    {
                        "name": "plan",
                        "status": "completed",
                        "output": {"meta_workspace": "3"},
                    },
                    {"name": "execute", "status": "in_progress"},
                ],
            },
            "prompt_step_000_plan.json": {
                "workflow_name": "deploy",
                "step_name": "plan",
                "step_type": "agent",
                "status": "completed",
                "step_index": 0,
                "total_steps": 2,
                "output": {"meta_workspace": "3"},
                "artifacts_dir": str(artifact_dir),
            },
            "prompt_step_001_execute.json": {
                "workflow_name": "deploy",
                "step_name": "execute",
                "step_type": "agent",
                "status": "in_progress",
                "step_index": 1,
                "total_steps": 2,
                "artifacts_dir": str(artifact_dir),
            },
            "plan_path.json": {"plan_path": "/tmp/wf-plan.md"},
        },
    )
    full_snapshot, compact_snapshot = _snapshots(projects_root, artifact_dir)

    full_agents = load_workflow_agents_from_snapshot(full_snapshot)
    compact_agents = load_compact_workflow_agents_from_snapshot(compact_snapshot)
    assert len(full_agents) == len(compact_agents) == 1
    _assert_parity(full_agents[0], compact_agents[0])
    compact = compact_agents[0]
    assert compact.workflow == "deploy"
    assert compact.appears_as_agent is True
    assert compact.is_anonymous is False
    assert compact.activity == "deploying"
    # Dead PID with an in-progress step keeps the row RUNNING on both paths.
    assert compact.status == "RUNNING"
    assert compact_agents[0].step_output == {"meta_workspace": "3"}

    full_steps, _ = load_workflow_agent_steps_from_snapshot(full_snapshot)
    compact_steps, _ = load_compact_workflow_agent_steps_from_snapshot(compact_snapshot)
    assert len(full_steps) == len(compact_steps) == 2
    for full_step, compact_step in zip(
        sorted(full_steps, key=lambda a: a.step_name or ""),
        sorted(compact_steps, key=lambda a: a.step_name or ""),
        strict=True,
    ):
        _assert_parity(full_step, compact_step)
    children = {a.step_name: a for a in compact_steps}
    assert children["execute"].status == "RUNNING"
    assert children["plan"].status == "DONE"
    assert children["plan"].parent_workflow == "deploy"


def test_failed_parent_and_step_parity(tmp_path: Path) -> None:
    ts = "20261117130100"
    artifact_dir = _layout(tmp_path, "myproj", "workflow-broken", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "broken-agent", "cl_name": "cl-broken"},
            "workflow_state.json": {
                "workflow_name": "broken",
                "status": "failed",
                "pid": None,
                "error": "workflow blew up",
                "traceback": "Traceback: wf",
                "current_step_index": 0,
                "steps": [
                    {
                        "name": "execute",
                        "status": "failed",
                        "error": "kaboom",
                        "traceback": "Traceback: kaboom",
                        "output": {"meta_note": "kept"},
                    },
                ],
            },
            "prompt_step_000_execute.json": {
                "workflow_name": "broken",
                "step_name": "execute",
                "step_type": "agent",
                "status": "in_progress",
                "step_index": 0,
                "total_steps": 1,
                "output": {"meta_note": "kept", "raw_blob": "deferred"},
                "error": None,
                "artifacts_dir": str(artifact_dir),
            },
        },
    )
    full_snapshot, compact_snapshot = _snapshots(projects_root, artifact_dir)

    full_agents = load_workflow_agents_from_snapshot(full_snapshot)
    compact_agents = load_compact_workflow_agents_from_snapshot(compact_snapshot)
    assert len(full_agents) == len(compact_agents) == 1
    full_parent, compact_parent = full_agents[0], compact_agents[0]
    assert full_parent.status == "FAILED" == compact_parent.status
    assert compact_parent.error_message == "workflow blew up"
    # Traceback is deferred detail on the compact path.
    assert full_parent.error_traceback == "Traceback: wf"
    assert compact_parent.error_traceback is None
    for name in (
        "status",
        "cl_name",
        "error_message",
        "workflow",
        "activity",
        "output_path",
    ):
        assert getattr(full_parent, name) == getattr(compact_parent, name), name

    full_steps, _ = load_workflow_agent_steps_from_snapshot(full_snapshot)
    compact_steps, _ = load_compact_workflow_agent_steps_from_snapshot(compact_snapshot)
    assert len(full_steps) == len(compact_steps) == 1
    full_step, compact_step = full_steps[0], compact_steps[0]
    # Parent failure propagates RUNNING -> FAILED with the parent error.
    assert full_step.status == "FAILED" == compact_step.status
    assert full_step.error_message == "workflow blew up"
    assert compact_step.error_message == "workflow blew up"
    # Full step output keeps detail keys. Compact facts retain only the
    # inventoried, typed list/action metadata keys.
    assert full_step.step_output == {"meta_note": "kept", "raw_blob": "deferred"}
    assert compact_step.step_output == {}


def test_monitor_member_process_identity_parity(tmp_path: Path) -> None:
    """Monitor members keep supervisor-stamped identity on the compact path.

    PID-reuse detection (capacity claims, dead-PID filtering) reads
    ``process_identity`` at list time. Monitor members usually carry no
    top-level identity; the supervisor stamps ``monitor_supervisor_identity``
    instead. The compact constructor must resolve the same value as the
    full snapshot loader.
    """
    ts = "20261117130600"
    artifact_dir = _layout(tmp_path, "myproj", "workflow-mon", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {
                "name": "mon-agent",
                "cl_name": "cl-mon",
                "pid": 12345,
                "run_started_at": "2026-11-17T11:00:01Z",
                "agent_session": "sess-mon",
                "agent_session_role": "monitor",
                "monitor_id": "turn-0",
                "monitor_state": "running",
                "monitor_start_status": "TESTING",
                "monitor_stop_status": "TESTED",
                "monitor_supervisor_identity": "boot:99",
            },
            "workflow_state.json": {
                "workflow_name": "mon",
                "status": "running",
                "pid": None,
                "current_step_index": 0,
                "appears_as_agent": True,
                "steps": [{"name": "watch", "status": "in_progress"}],
            },
        },
    )
    full_snapshot, compact_snapshot = _snapshots(projects_root, artifact_dir)
    full_agents = load_workflow_agents_from_snapshot(full_snapshot)
    compact_agents = load_compact_workflow_agents_from_snapshot(compact_snapshot)
    assert len(full_agents) == len(compact_agents) == 1
    full_agent, compact_agent = full_agents[0], compact_agents[0]
    assert full_agent.is_monitor and compact_agent.is_monitor
    assert full_agent.process_identity == "boot:99"
    assert compact_agent.process_identity == "boot:99"
    assert compact_agent.status == full_agent.status == "TESTING"
    _assert_parity(full_agent, compact_agent)


def test_settled_session_turn_suppresses_workflow_parent(tmp_path: Path) -> None:
    ts = "20261117130200"
    artifact_dir = _layout(tmp_path, "myproj", "workflow-monitored", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "mon-agent", "cl_name": "cl-mon"},
            "workflow_state.json": {
                "workflow_name": "monitored",
                "status": "completed",
                "current_step_index": 0,
                "steps": [{"name": "watch", "status": "completed"}],
            },
            "done.json": {"outcome": "monitored", "cl_name": "cl-mon"},
        },
    )
    full_snapshot, compact_snapshot = _snapshots(projects_root, artifact_dir)
    assert load_workflow_agents_from_snapshot(full_snapshot) == []
    assert load_compact_workflow_agents_from_snapshot(compact_snapshot) == []


def test_hydration_restores_deferred_workflow_detail(
    tmp_path: Path, monkeypatch: Any
) -> None:
    ts = "20261117130300"
    artifact_dir = _layout(tmp_path, "home", "workflow-hydra", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "hydra-agent", "cl_name": "cl-hydra"},
            "workflow_state.json": {
                "workflow_name": "hydra",
                "status": "failed",
                "current_step_index": 0,
                "steps": [
                    {
                        "name": "execute",
                        "status": "failed",
                        "error": "nope",
                        "traceback": "Traceback: nope",
                        "output": {
                            "meta_note": "kept",
                            "raw_blob": "deferred",
                            "diff_path": "/tmp/hydra.diff",
                        },
                    },
                ],
            },
            "prompt_step_000_execute.json": {
                "workflow_name": "hydra",
                "step_name": "execute",
                "step_type": "agent",
                "status": "failed",
                "step_index": 0,
                "total_steps": 1,
                "output": {"meta_note": "kept", "raw_blob": "deferred"},
                "error": "nope",
                "traceback": "Traceback: nope",
                "response_path": "/tmp/hydra-reply.md",
                "artifacts_dir": str(artifact_dir),
            },
        },
    )
    full_snapshot, compact_snapshot = _snapshots(projects_root, artifact_dir)
    compact_steps, _ = load_compact_workflow_agent_steps_from_snapshot(compact_snapshot)
    compact_parents = load_compact_workflow_agents_from_snapshot(compact_snapshot)
    assert len(compact_steps) == 1 and len(compact_parents) == 1
    step = compact_steps[0]
    parent = compact_parents[0]
    assert step.record_shape == "list" and step.index_record_dir
    assert step.response_path is None
    assert step.error_traceback is None
    assert parent.error_traceback is None

    # Hydration loads the exact full record; serve the scratch-tree record
    # for the selected artifact dir instead of touching the real index.
    import sase.ace.tui.models._projected_record_load as projected

    full_record = full_snapshot.records[0]
    assert full_record.artifact_dir == step.index_record_dir

    def _fake_load(index_path: Any, artifact_dirs: Any, **kwargs: Any) -> list[Any]:
        assert list(artifact_dirs) == [step.index_record_dir]
        return [full_record]

    monkeypatch.setattr(projected, "load_agent_artifact_records", _fake_load)
    monkeypatch.setattr(
        projected, "default_agent_artifact_index_path", lambda: Path("/tmp/idx.sqlite")
    )
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    assert hydrate_projected_agent(step) is True
    assert step.record_shape == "full"
    # Deferred step detail converges to the full row: complete step output,
    # response path, and the step traceback.
    assert step.step_output == {
        "meta_note": "kept",
        "raw_blob": "deferred",
    }
    assert step.response_path == "/tmp/hydra-reply.md"
    assert step.error_traceback == "Traceback: nope"

    assert hydrate_projected_agent(parent) is True
    assert parent.error_traceback == "Traceback: nope"


def test_compact_workflow_shapes_and_guards(tmp_path: Path) -> None:
    ts = "20261117130400"
    artifact_dir = _layout(tmp_path, "myproj", "workflow-guard", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "guard-agent", "cl_name": "cl-guard"},
            "workflow_state.json": {
                "workflow_name": "guard",
                "status": "running",
                "current_step_index": 0,
                "appears_as_agent": False,
                "is_anonymous": True,
                "hidden": True,
                "steps": [{"name": "s", "status": "in_progress"}],
            },
            "prompt_step_000_s.json": {
                "workflow_name": "guard",
                "step_name": "s",
                "step_type": "agent",
                "status": "in_progress",
                "step_index": 0,
                "total_steps": 1,
                "is_pre_prompt_step": True,
                "artifacts_dir": str(artifact_dir),
            },
        },
    )
    full_snapshot, compact_snapshot = _snapshots(projects_root, artifact_dir)
    assert is_compact_workflow_state_record(compact_snapshot.records[0]) is True
    assert is_compact_workflow_state_record(full_snapshot.records[0]) is True

    compact_agents = load_compact_workflow_agents_from_snapshot(compact_snapshot)
    assert len(compact_agents) == 1
    parent = compact_agents[0]
    assert parent.is_anonymous is True
    assert parent.hidden is True

    compact_steps, _ = load_compact_workflow_agent_steps_from_snapshot(compact_snapshot)
    assert len(compact_steps) == 1
    # Pre-prompt steps stay hidden on both paths.
    assert compact_steps[0].is_hidden_step is True


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("full-record path must not be used")


def test_compact_workflow_path_does_not_use_full_decoder(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr("sase.core.agent_scan_wire_conversion._record_from_dict", _boom)
    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._workflow_snapshot_loaders."
        "load_workflow_agents_from_snapshot",
        _boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._workflow_snapshot_loaders."
        "load_workflow_agent_steps_from_snapshot",
        _boom,
    )
    ts = "20261117130500"
    artifact_dir = _layout(tmp_path, "myproj", "workflow-boom", ts)
    projects_root = tmp_path / "projects"
    _write_markers(
        artifact_dir,
        {
            "agent_meta.json": {"name": "boom-agent", "cl_name": "cl-boom"},
            "workflow_state.json": {
                "workflow_name": "boom",
                "status": "running",
                "current_step_index": 0,
                "steps": [{"name": "s", "status": "in_progress"}],
            },
        },
    )
    compact = scan_agent_artifact_dirs_list(projects_root, [artifact_dir])
    agents = load_compact_workflow_agents_from_snapshot(compact)
    assert len(agents) == 1 and agents[0].workflow == "boom"

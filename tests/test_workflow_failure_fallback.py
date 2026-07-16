"""Tests for FAILED workflow fallback output in filesystem and wire loaders."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models._loaders._workflow_failure_fallback import (
    _read_output_tail_cached,
    _workflow_output_candidates,
    build_workflow_failure_fallback,
)
from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_states
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agents_from_snapshot,
    load_workflow_states_from_snapshot,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    WorkflowStateWire,
)


def _filesystem_workflow(
    tmp_path: Path,
    *,
    state: dict[str, object],
) -> tuple[Path, Path]:
    project_dir = tmp_path / "projects" / "demo"
    artifact_dir = project_dir / "artifacts" / "ace-run" / "20260715123456"
    artifact_dir.mkdir(parents=True)
    (project_dir / "demo.sase").touch()
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    return project_dir, artifact_dir


def _snapshot(
    tmp_path: Path,
    *,
    output_path: str | None,
    error: str | None = None,
) -> AgentArtifactScanWire:
    artifact_dir = tmp_path / "projects/demo/artifacts/ace-run/20260715123456"
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(tmp_path / "projects"),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="demo",
                project_dir=str(tmp_path / "projects/demo"),
                project_file=str(tmp_path / "projects/demo/demo.sase"),
                workflow_dir_name="ace-run",
                artifact_dir=str(artifact_dir),
                timestamp="20260715123456",
                agent_meta=AgentMetaWire(output_path=output_path),
                workflow_state=WorkflowStateWire(
                    workflow_name="ace(run)",
                    cl_name="demo/change",
                    status="running",
                    pid=12345,
                    error=error,
                ),
            )
        ],
    )


def test_filesystem_failed_workflow_uses_last_40_output_lines(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "runner.log"
    log_path.write_text(
        "".join(f"output line {line:02d}\n" for line in range(50)),
        encoding="utf-8",
    )
    project_dir, artifact_dir = _filesystem_workflow(
        tmp_path,
        state={
            "workflow_name": "ace(run)",
            "status": "running",
            "pid": 12345,
            "context": {"cl_name": "demo/change"},
            "steps": [],
        },
    )
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"output_path": str(log_path)}), encoding="utf-8"
    )

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
        return_value=False,
    ):
        entries = load_workflow_states(timestamp_dirs=[(project_dir, artifact_dir)])

    assert len(entries) == 1
    entry = entries[0]
    assert entry.status == "FAILED"
    assert entry.output_path == str(log_path)
    assert entry.error_message is not None
    assert "Runner exited without recording an error" in entry.error_message
    assert "output line 10" in entry.error_message
    assert "output line 09" not in entry.error_message
    assert entry.error_message.endswith("output line 49")


def test_snapshot_failed_workflow_names_missing_output_path(
    tmp_path: Path,
) -> None:
    missing_log = tmp_path / "missing-runner.log"
    snapshot = _snapshot(tmp_path, output_path=str(missing_log))

    with patch(
        "sase.ace.tui.models._loaders._workflow_snapshot_loaders.is_process_running",
        return_value=False,
    ):
        entries = load_workflow_states_from_snapshot(snapshot)
        agents = load_workflow_agents_from_snapshot(snapshot)

    assert entries[0].status == "FAILED"
    assert entries[0].error_message is not None
    assert "No runner output was available" in entries[0].error_message
    assert str(missing_log) in entries[0].error_message
    assert entries[0].output_path == str(missing_log)
    assert agents[0].error_message == entries[0].error_message
    assert agents[0].output_path == str(missing_log)


def test_recorded_workflow_error_is_not_replaced(tmp_path: Path) -> None:
    log_path = tmp_path / "runner.log"
    project_dir, artifact_dir = _filesystem_workflow(
        tmp_path,
        state={
            "workflow_name": "ace(run)",
            "status": "failed",
            "pid": 12345,
            "context": {"cl_name": "demo/change"},
            "steps": [],
            "error": "recorded failure",
        },
    )
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"output_path": str(log_path)}), encoding="utf-8"
    )

    entries = load_workflow_states(timestamp_dirs=[(project_dir, artifact_dir)])

    assert entries[0].error_message == "recorded failure"
    assert entries[0].output_path == str(log_path)


def test_output_tail_cache_hits_for_unchanged_file(tmp_path: Path) -> None:
    log_path = tmp_path / "runner.log"
    log_path.write_text("last output\n", encoding="utf-8")
    _read_output_tail_cached.cache_clear()

    first = build_workflow_failure_fallback(
        cl_name="demo",
        launch_timestamp="20260715123456",
        recorded_output_path=str(log_path),
    )
    before = _read_output_tail_cached.cache_info()
    second = build_workflow_failure_fallback(
        cl_name="demo",
        launch_timestamp="20260715123456",
        recorded_output_path=str(log_path),
    )
    after = _read_output_tail_cached.cache_info()

    assert first == second
    assert after.hits == before.hits + 1


def test_output_path_derivation_matches_launch_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))

    candidates = _workflow_output_candidates(
        cl_name="feature/test:1",
        launch_timestamp="20260715123456",
        recorded_output_path=None,
    )

    assert candidates == (
        str(
            tmp_path
            / "sase-home/workflows/202607/feature_test_1_ace-run-260715_123456.txt"
        ),
    )

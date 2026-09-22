from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._agent_loader_artifacts import query_artifact_index_for_loader
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact_dir(projects: Path, timestamp: str) -> Path:
    return projects / "proj" / "artifacts" / "ace-run" / timestamp


def _home_running_dir(projects: Path, timestamp: str) -> Path:
    return projects / "home" / "artifacts" / "ace-run" / timestamp


def test_windowed_loader_keeps_completed_when_active_exceeds_limit(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    for timestamp in (
        "20260827090000",
        "20260827090100",
        "20260827090200",
        "20260827090300",
        "20260827090400",
    ):
        artifact_dir = _home_running_dir(projects, timestamp)
        _write_json(
            artifact_dir / "agent_meta.json",
            {"name": f"active-{timestamp}", "pid": 42},
        )
        _write_json(artifact_dir / "running.json", {"pid": 42})
    for timestamp in ("20260827090500", "20260827090600", "20260827090700"):
        artifact_dir = _artifact_dir(projects, timestamp)
        _write_json(
            artifact_dir / "agent_meta.json",
            {"name": f"done-{timestamp}"},
        )
        _write_json(
            artifact_dir / "done.json",
            {"outcome": "completed", "name": f"done-{timestamp}"},
        )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects)

    snapshot, state = query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=2,
        default_index_path=lambda: index_path,
        projects_root=lambda: projects,
        query_index=query_agent_artifact_index,
        scan_artifacts=lambda options=None: scan_agent_artifacts(projects, options),
    )

    timestamps = {record.timestamp for record in snapshot.records}
    assert timestamps == {
        "20260827090000",
        "20260827090100",
        "20260827090200",
        "20260827090300",
        "20260827090400",
        "20260827090600",
        "20260827090700",
    }
    assert "20260827090500" not in timestamps
    assert state.bounded_prefix is True
    assert state.has_more is True
    assert state.record_count == 7
    window = snapshot.index_window
    assert window is not None
    assert window.active_candidate_count == 5
    assert window.completed_candidate_count == 3
    assert window.selected_candidate_count == 7

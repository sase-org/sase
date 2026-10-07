"""Unit tests for the shared waiting-marker walk and runner liveness."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.axe.wait_marker_scan import (
    scan_waiting_markers,
    waiting_runner_liveness,
)
from sase.core.process_identity import process_identity_token
from tests._agent_names_fixtures import DEAD_PID


def _write_marker(
    projects_root: Path,
    project: str,
    suffix: str,
    *,
    waiting_for: list[str] | None = None,
    ready: bool = False,
    meta: dict | None = None,
    running: dict | None = None,
) -> Path:
    artifact_dir = projects_root / project / "artifacts" / "ace-run" / suffix
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": waiting_for or ["foo"], "cl_name": "waiter"}),
        encoding="utf-8",
    )
    if ready:
        (artifact_dir / "ready.json").write_text("{}\n", encoding="utf-8")
    if meta is not None:
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )
    if running is not None:
        (artifact_dir / "running.json").write_text(
            json.dumps(running), encoding="utf-8"
        )
    return artifact_dir


def test_scan_partitions_pending_and_already_ready(tmp_path: Path) -> None:
    pending = _write_marker(tmp_path, "proj", "pending")
    _write_marker(tmp_path, "proj", "released", ready=True)
    idle = tmp_path / "proj" / "artifacts" / "ace-run" / "idle"
    idle.mkdir(parents=True)

    scan = scan_waiting_markers(tmp_path)

    assert scan.projects == 1
    assert scan.artifacts == 3
    assert scan.waiting == 2
    assert scan.already_ready == 1
    assert [marker.waiting_path.parent for marker in scan.pending] == [pending]
    assert len(scan.already_ready_markers) == 1
    assert scan.walked_dirs == {
        pending,
        idle,
        tmp_path / "proj" / "artifacts" / "ace-run" / "released",
    }


def test_scan_ignores_agent_meta_content(tmp_path: Path) -> None:
    pending = _write_marker(tmp_path, "proj", "waiter")
    # Corrupt metadata must not disturb the marker walk: classification is
    # the caller's job, using its own meta cache.
    (pending / "agent_meta.json").write_text("not json\n", encoding="utf-8")

    scan = scan_waiting_markers(tmp_path)

    assert [marker.waiting_path.parent for marker in scan.pending] == [pending]
    assert scan.already_ready == 0


def test_liveness_missing_meta_is_unknown(tmp_path: Path) -> None:
    assert waiting_runner_liveness(tmp_path, None) == "unknown"


def test_liveness_missing_pid_is_unknown(tmp_path: Path) -> None:
    assert waiting_runner_liveness(tmp_path, {"name": "x"}) == "unknown"
    assert waiting_runner_liveness(tmp_path, {"pid": "123"}) == "unknown"
    assert waiting_runner_liveness(tmp_path, {"pid": True}) == "unknown"


def test_liveness_stopped_at_is_dead(tmp_path: Path) -> None:
    meta = {"pid": os.getpid(), "stopped_at": "2026-01-01T00:00:00+00:00"}
    assert waiting_runner_liveness(tmp_path, meta) == "dead"


def test_liveness_dead_pid_is_dead(tmp_path: Path) -> None:
    assert waiting_runner_liveness(tmp_path, {"pid": DEAD_PID}) == "dead"


def test_liveness_running_json_fallback_pid(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "waiter"
    artifact_dir.mkdir()
    (artifact_dir / "agent_meta.json").write_text("{}\n", encoding="utf-8")
    (artifact_dir / "running.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_identity": process_identity_token(os.getpid()),
            }
        ),
        encoding="utf-8",
    )

    assert waiting_runner_liveness(artifact_dir, {}) == "alive"


def test_liveness_running_json_dead_pid_is_dead(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "waiter"
    artifact_dir.mkdir()
    (artifact_dir / "running.json").write_text(
        json.dumps({"pid": DEAD_PID}), encoding="utf-8"
    )

    assert waiting_runner_liveness(artifact_dir, {"name": "x"}) == "dead"


def test_liveness_live_pid_is_alive(tmp_path: Path) -> None:
    meta = {
        "pid": os.getpid(),
        "process_identity": process_identity_token(os.getpid()),
    }
    assert waiting_runner_liveness(tmp_path, meta) == "alive"


def test_liveness_reused_pid_is_dead(tmp_path: Path) -> None:
    meta = {"pid": os.getpid(), "process_identity": "0:0"}
    assert waiting_runner_liveness(tmp_path, meta) == "dead"


def test_liveness_failure_fails_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_meta: dict, _artifact_dir: Path) -> bool:
        raise PermissionError("liveness unavailable")

    monkeypatch.setattr("sase.axe.wait_marker_scan.is_process_alive", _boom)

    assert waiting_runner_liveness(tmp_path, {"pid": os.getpid()}) == "unknown"

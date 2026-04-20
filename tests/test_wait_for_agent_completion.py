"""Tests for sase.agent.names.wait_for_agent_completion."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import wait_for_agent_completion

_DEAD_PID = 99_999_999


def _make_running_agent(base: Path, project: str, suffix: str, name: str) -> Path:
    artifact_dir = (
        base / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta = {"name": name, "pid": os.getpid(), "model": "test"}
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    return artifact_dir


def _make_dead_agent(base: Path, project: str, suffix: str, name: str) -> Path:
    artifact_dir = (
        base / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta = {"name": name, "pid": _DEAD_PID, "model": "test"}
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    return artifact_dir


class TestWaitForAgentCompletion:
    def test_returns_immediately_when_done_json_present(self, tmp_path: Path) -> None:
        artifact_dir = _make_running_agent(tmp_path, "proj", "run1", "foo")
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))

        with patch.object(Path, "home", return_value=tmp_path):
            start = time.monotonic()
            wait_for_agent_completion("foo", poll_interval=0.01)
            elapsed = time.monotonic() - start

        assert elapsed < 1.0

    def test_returns_when_done_json_appears(self, tmp_path: Path) -> None:
        artifact_dir = _make_running_agent(tmp_path, "proj", "run1", "foo")

        def write_done_later() -> None:
            time.sleep(0.1)
            (artifact_dir / "done.json").write_text(
                json.dumps({"outcome": "completed"})
            )

        t = threading.Thread(target=write_done_later, daemon=True)
        t.start()
        try:
            with patch.object(Path, "home", return_value=tmp_path):
                wait_for_agent_completion("foo", poll_interval=0.05)
        finally:
            t.join(timeout=2)

        assert (artifact_dir / "done.json").exists()

    def test_returns_when_pid_dies_without_done(self, tmp_path: Path) -> None:
        _make_dead_agent(tmp_path, "proj", "run1", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            start = time.monotonic()
            wait_for_agent_completion("foo", poll_interval=0.01)
            elapsed = time.monotonic() - start

        assert elapsed < 2.0

    def test_polls_until_artifact_dir_appears(self, tmp_path: Path) -> None:
        def create_agent_later() -> None:
            time.sleep(0.15)
            artifact_dir = _make_running_agent(tmp_path, "proj", "run1", "foo")
            (artifact_dir / "done.json").write_text(
                json.dumps({"outcome": "completed"})
            )

        t = threading.Thread(target=create_agent_later, daemon=True)
        t.start()
        try:
            with patch.object(Path, "home", return_value=tmp_path):
                wait_for_agent_completion("foo", poll_interval=0.05, find_timeout=5.0)
        finally:
            t.join(timeout=2)

        projects_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
        )
        assert any(d.is_dir() for d in projects_dir.iterdir())

    def test_find_timeout_returns_without_hanging(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            start = time.monotonic()
            wait_for_agent_completion(
                "never-appears", poll_interval=0.05, find_timeout=0.2
            )
            elapsed = time.monotonic() - start

        assert 0.1 <= elapsed < 2.0

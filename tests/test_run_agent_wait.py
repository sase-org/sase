"""Tests for pre-run wait marker lifecycle."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_wait import wait_for_dependencies


def test_successful_wait_records_completion_before_cleanup(tmp_path: Path) -> None:
    """wait_completed_at is durable before waiting.json is removed."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")
    original_unlink = os.unlink
    saw_waiting_unlink = False

    def unlink(path: str) -> None:
        nonlocal saw_waiting_unlink
        if Path(path).name == "waiting.json":
            saw_waiting_unlink = True
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert isinstance(data.get("wait_completed_at"), str)
            assert data["wait_completed_at"]
        original_unlink(path)

    agent_meta = {"pid": 123}
    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.os.unlink", side_effect=unlink),
    ):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            agent_meta,
            duration=0,
        )

    assert saw_waiting_unlink is True
    assert isinstance(agent_meta.get("wait_completed_at"), str)
    assert not (tmp_path / "waiting.json").exists()


def test_dependency_wait_updates_index_for_waiting_marker_only(
    tmp_path: Path,
) -> None:
    """waiting.json write/removal refreshes; ready.json removal does not."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 123}))
    (tmp_path / "ready.json").write_text("{}")
    calls: list[str] = []

    def write_agent_meta(artifacts_dir: str, agent_meta: dict) -> None:
        (Path(artifacts_dir) / "agent_meta.json").write_text(json.dumps(agent_meta))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.write_agent_meta", write_agent_meta),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        wait_for_dependencies(
            ["dep"],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
        )

    assert calls == [str(tmp_path), str(tmp_path)]
    assert not (tmp_path / "waiting.json").exists()
    assert not (tmp_path / "ready.json").exists()


def test_killed_wait_does_not_record_completion(tmp_path: Path) -> None:
    """A kill during the wait does not mark the wait as successfully crossed."""
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=True),
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=1,
        )

    assert exc_info.value.code == 143
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "wait_completed_at" not in data
    assert not (tmp_path / "waiting.json").exists()


def test_killed_wait_updates_index_for_write_and_cleanup(tmp_path: Path) -> None:
    calls: list[str] = []

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=True),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            [],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=1,
        )

    assert exc_info.value.code == 143
    assert calls == [str(tmp_path), str(tmp_path)]
    assert not (tmp_path / "waiting.json").exists()

"""Tests for pre-run wait marker lifecycle."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_wait import wait_for_dependencies

from tests._agent_names_fixtures import make_agent


def _make_waiter(base: Path, project: str = "proj") -> Path:
    artifact_dir = base / ".sase/projects" / project / "artifacts/ace-run/waiter"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 123}),
        encoding="utf-8",
    )
    return artifact_dir


def test_resolved_named_wait_skips_waiting_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "dep",
        done=True,
        outcome="completed",
    )
    waiter_dir = _make_waiter(tmp_path)
    agent_meta = {"pid": 123}
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: index_updates.append(path),
        ),
        patch("sase.axe.run_agent_wait.time.sleep") as sleep_mock,
    ):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )

    sleep_mock.assert_not_called()
    assert index_updates == []
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()
    assert isinstance(agent_meta.get("wait_completed_at"), str)
    disk_meta = json.loads((waiter_dir / "agent_meta.json").read_text())
    assert disk_meta["wait_completed_at"] == agent_meta["wait_completed_at"]


def test_unresolved_named_wait_uses_slow_waiting_marker_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: index_updates.append(path),
        ),
    ):
        wait_for_dependencies(
            ["missing"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
        )

    assert index_updates == [str(waiter_dir), str(waiter_dir)]
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize(
    "wait_kwargs",
    [
        {"duration": 0},
        {"wait_until": "2000-01-01T00:00:00"},
    ],
)
def test_named_wait_with_time_floor_uses_slow_waiting_marker_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wait_kwargs: dict[str, float | str],
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "dep",
        done=True,
        outcome="completed",
    )
    waiter_dir = _make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    index_updates: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: index_updates.append(path),
        ),
    ):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            **wait_kwargs,
        )

    assert index_updates == [str(waiter_dir), str(waiter_dir)]
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


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

"""Tests for blocking run-agent waits (beads, hoods, ready markers)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_wait import wait_for_dependencies

from tests._agent_names_fixtures import make_agent
from tests._run_agent_wait_helpers import make_waiter, patch_index_updates


def test_bead_only_wait_writes_marker_and_names_only_beads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter_dir = make_waiter(tmp_path)
    ready_path = waiter_dir / "ready.json"
    marker_snapshots: list[dict[str, object]] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def publish_ready_after_poll(_seconds: float) -> None:
        marker_snapshots.append(
            json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
        )
        ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.bead.store_locator.closed_bead_ids_for_project",
            return_value=frozenset(),
        ),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=publish_ready_after_poll,
        ),
    ):
        blocked = wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260720120000",
            {"pid": 123},
            project_name="proj",
            wait_beads=["sase-87.3"],
        )

    assert blocked is True
    assert marker_snapshots == [
        {
            "waiting_for": [],
            "patch_name": "cl",
            "cl_name": "cl",
            "timestamp": "20260720120000",
            "wait_for_beads": ["sase-87.3"],
        }
    ]
    output = capsys.readouterr().out
    assert "Waiting for beads: sase-87.3" in output
    assert "agents:" not in output


def test_hood_only_wait_writes_marker_and_names_only_hoods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260720110000",
        "sase-11l.member",
        done=False,
    )
    waiter_dir = make_waiter(tmp_path)
    ready_path = waiter_dir / "ready.json"
    marker_snapshots: list[dict[str, object]] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def publish_ready_after_poll(_seconds: float) -> None:
        marker_snapshots.append(
            json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
        )
        ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=publish_ready_after_poll,
        ),
    ):
        blocked = wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260720120000",
            {"pid": 123},
            project_name="proj",
            wait_hoods=["sase-11l"],
        )

    assert blocked is True
    assert marker_snapshots == [
        {
            "waiting_for": [],
            "patch_name": "cl",
            "cl_name": "cl",
            "timestamp": "20260720120000",
            "wait_for_hoods": ["sase-11l"],
        }
    ]
    output = capsys.readouterr().out
    assert "Waiting for hoods: sase-11l" in output
    assert "agents:" not in output


def test_unresolved_named_wait_blocks_until_ready_marker_arrives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiter(tmp_path)
    ready_path = waiter_dir / "ready.json"
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def resolve_after_poll(_seconds: float) -> None:
        ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=resolve_after_poll,
        ),
    ):
        blocked = wait_for_dependencies(
            ["missing"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
        )

    assert blocked is True
    assert not ready_path.exists()


def test_stale_cancelled_ready_marker_is_removed_and_wait_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = make_waiter(tmp_path)
    (waiter_dir / "ready.json").write_text(
        json.dumps(
            {
                "cancelled": True,
                "reason": "dependency_failed",
                "failed_deps": [
                    {
                        "name": "foo",
                        "timestamp": "20260506010101",
                        "project_name": "proj",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def resolve_after_stale_marker_is_removed(_seconds: float) -> None:
        assert not (waiter_dir / "ready.json").exists()
        (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=resolve_after_stale_marker_is_removed,
        ) as sleep_mock,
    ):
        wait_for_dependencies(
            ["foo"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            wait_identity_deps=[
                {
                    "project_name": "proj",
                    "timestamp": "20260506010101",
                    "name": "foo",
                }
            ],
        )

    sleep_mock.assert_called_once_with(2)
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


def test_failed_identity_dependency_waits_until_waiter_is_killed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="killed",
    )
    waiter_dir = make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    killed = False

    def was_killed() -> bool:
        return killed

    def kill_waiter_after_one_poll(_seconds: float) -> None:
        nonlocal killed
        assert (waiter_dir / "waiting.json").exists()
        assert not (waiter_dir / "ready.json").exists()
        killed = True

    with (
        patch("sase.axe.run_agent_wait.was_killed", side_effect=was_killed),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=kill_waiter_after_one_poll,
        ) as sleep_mock,
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            ["foo"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            wait_identity_deps=[
                {
                    "project_name": "proj",
                    "timestamp": parent_dir.name,
                    "artifact_dir": str(parent_dir),
                    "name": "foo",
                }
            ],
        )

    assert exc_info.value.code == 143
    sleep_mock.assert_called_once_with(2)
    assert not (waiter_dir / "waiting.json").exists()


def test_named_duration_wait_starts_after_dependencies_are_ready(
    tmp_path: Path,
) -> None:
    """A relative duration is not consumed by time spent waiting on deps."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 123}))
    ready_path = tmp_path / "ready.json"
    sleep_calls: list[float] = []
    marker_snapshots: list[dict[str, object]] = []

    def update_index(artifacts_dir: str) -> None:
        waiting_path = Path(artifacts_dir) / "waiting.json"
        if waiting_path.exists():
            marker_snapshots.append(json.loads(waiting_path.read_text()))

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) == 2:
            ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch_index_updates(update_index),
        patch("sase.axe.run_agent_wait.time.sleep", side_effect=sleep),
        patch(
            "sase.axe.run_agent_wait.remaining_until",
            side_effect=[3.0, 1.0, 0.0],
        ),
    ):
        wait_for_dependencies(
            ["dep"],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=3,
        )

    assert sleep_calls == [2, 2, 2, 1]
    assert len(marker_snapshots) == 2
    assert marker_snapshots[0]["waiting_for"] == ["dep"]
    assert marker_snapshots[0]["wait_duration"] == 3
    assert "wait_until" not in marker_snapshots[0]
    assert marker_snapshots[1]["wait_duration"] == 3
    assert isinstance(marker_snapshots[1].get("wait_until"), str)
    assert not (tmp_path / "waiting.json").exists()
    assert not ready_path.exists()

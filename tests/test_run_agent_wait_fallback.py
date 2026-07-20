"""Tests for waiting-runner fallback dependency resolution."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_wait import wait_for_dependencies

from tests._agent_names_fixtures import make_agent


@pytest.fixture(autouse=True)
def _disable_real_axe_ensure() -> Iterator[None]:
    """Keep wait-loop tests isolated from the host axe daemon."""
    with patch("sase.axe.run_agent_wait._opportunistic_ensure_axe"):
        yield


def _make_waiter(base: Path) -> Path:
    artifact_dir = base / ".sase/projects/proj/artifacts/ace-run/waiter"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 123}),
        encoding="utf-8",
    )
    return artifact_dir


def test_named_wait_fallback_resolves_without_ready_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dep_dir = make_agent(tmp_path, "proj", "20260506010101", "dep")
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    sleep_calls: list[float] = []

    def complete_dependency_after_poll(seconds: float) -> None:
        sleep_calls.append(seconds)
        assert not (waiter_dir / "ready.json").exists()
        (dep_dir / "done.json").write_text(
            json.dumps({"outcome": "completed"}),
            encoding="utf-8",
        )

    agent_meta = {"pid": 123}
    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=complete_dependency_after_poll,
        ),
    ):
        blocked = wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )

    assert blocked is True
    assert sleep_calls == [2]
    assert "Dependencies satisfied by runner fallback" in capsys.readouterr().out
    assert isinstance(agent_meta.get("wait_completed_at"), str)
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


def test_named_wait_fallback_honors_memoized_identity_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    identity_dep = {
        "project_name": "proj",
        "timestamp": "20260506010101",
        "artifact_dir": str(
            tmp_path / ".sase/projects/proj/artifacts/ace-run/20260506010101"
        ),
        "name": "dep",
    }

    def memoize_dependency_after_poll(_seconds: float) -> None:
        waiting_path = waiter_dir / "waiting.json"
        waiting_data = json.loads(waiting_path.read_text(encoding="utf-8"))
        waiting_data["resolved_deps"] = [identity_dep]
        waiting_path.write_text(json.dumps(waiting_data), encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=memoize_dependency_after_poll,
        ) as sleep_mock,
    ):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            wait_identity_deps=[identity_dep],
        )

    sleep_mock.assert_called_once_with(2)
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


def test_named_wait_fallback_starts_duration_floor_at_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dep_dir = make_agent(tmp_path, "proj", "20260506010101", "dep")
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    sleep_calls: list[float] = []
    marker_snapshots: list[dict[str, object]] = []

    def update_index(artifacts_dir: str) -> None:
        waiting_path = Path(artifacts_dir) / "waiting.json"
        if waiting_path.exists():
            marker_snapshots.append(json.loads(waiting_path.read_text()))

    def complete_dependency_on_first_poll(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) == 1:
            (dep_dir / "done.json").write_text(
                json.dumps({"outcome": "completed"}),
                encoding="utf-8",
            )

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation",
            side_effect=update_index,
        ),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=complete_dependency_on_first_poll,
        ),
        patch(
            "sase.axe.run_agent_wait.remaining_until",
            side_effect=[3.0, 0.0],
        ),
    ):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
            duration=3,
        )

    assert sleep_calls == [2, 2]
    assert len(marker_snapshots) == 2
    assert "wait_until" not in marker_snapshots[0]
    assert isinstance(marker_snapshots[1].get("wait_until"), str)
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()


def test_named_wait_fallback_keeps_waiting_while_dependency_is_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_agent(tmp_path, "proj", "20260506010101", "dep")
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    sleep_count = 0

    def was_killed() -> bool:
        return sleep_count >= 2

    def count_poll(_seconds: float) -> None:
        nonlocal sleep_count
        sleep_count += 1

    with (
        patch("sase.axe.run_agent_wait.was_killed", side_effect=was_killed),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch("sase.axe.run_agent_wait.time.sleep", side_effect=count_poll),
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            project_name="proj",
        )

    assert exc_info.value.code == 143
    assert sleep_count == 2
    assert "Dependencies satisfied by runner fallback" not in capsys.readouterr().out
    assert not (waiter_dir / "waiting.json").exists()
    assert not (waiter_dir / "ready.json").exists()
    disk_meta = json.loads((waiter_dir / "agent_meta.json").read_text())
    assert "wait_completed_at" not in disk_meta


def test_bead_wait_fallback_releases_after_bead_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    closed_beads: set[str] = set()
    sleep_calls: list[float] = []

    def close_bead_after_poll(seconds: float) -> None:
        sleep_calls.append(seconds)
        closed_beads.add("sase-87.3")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.bead.store_locator.closed_bead_ids_for_project",
            side_effect=lambda _project: frozenset(closed_beads),
        ),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=close_bead_after_poll,
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
    assert sleep_calls == [2]
    assert "Dependencies satisfied by runner fallback" in capsys.readouterr().out


def test_bead_wait_fallback_stays_parked_while_bead_is_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    sleep_count = 0

    def was_killed() -> bool:
        return sleep_count >= 2

    def count_poll(_seconds: float) -> None:
        nonlocal sleep_count
        sleep_count += 1

    with (
        patch("sase.axe.run_agent_wait.was_killed", side_effect=was_killed),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.bead.store_locator.closed_bead_ids_for_project",
            return_value=frozenset(),
        ),
        patch("sase.axe.run_agent_wait.time.sleep", side_effect=count_poll),
        pytest.raises(SystemExit) as exc_info,
    ):
        wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260720120000",
            {"pid": 123},
            project_name="proj",
            wait_beads=["sase-87.3"],
        )

    assert exc_info.value.code == 143
    assert sleep_count == 2


def test_named_wait_fallback_is_skipped_without_project_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 123}))
    ready_path = tmp_path / "ready.json"

    def publish_ready_after_poll(_seconds: float) -> None:
        ready_path.write_text("{}", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.axe.run_agent_wait._waiting_marker_dependencies_resolved"
        ) as fallback,
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=publish_ready_after_poll,
        ),
    ):
        wait_for_dependencies(
            ["dep"],
            str(tmp_path),
            "cl",
            "20260513120000",
            {"pid": 123},
        )

    fallback.assert_not_called()

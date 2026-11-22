"""Wait-loop eligibility and refreshed-pass tests for the lean waiter."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_wait import wait_for_dependencies


def _make_waiter(path: Path) -> Path:
    waiter = path / "waiter"
    waiter.mkdir()
    (waiter / "agent_meta.json").write_text(json.dumps({"pid": 123}), encoding="utf-8")
    return waiter


def test_dependency_wait_hands_off_after_thirty_seconds(
    tmp_path: Path,
) -> None:
    waiter = _make_waiter(tmp_path)
    handoffs: list[tuple[str, float | None, float]] = []

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.mark_lifecycle_phase"),
        patch("sase.axe.run_agent_wait.release_idle_memory"),
        patch(
            "sase.axe.run_agent_wait.resolve_initial_wait_release",
            return_value=SimpleNamespace(releasable=False, patch=None),
        ),
        patch("sase.axe.run_agent_wait.time.time", return_value=1000.0),
        patch(
            "sase.axe.run_agent_wait.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 31.0],
        ),
    ):
        blocked = wait_for_dependencies(
            ["missing"],
            str(waiter),
            "work",
            "20261122010101",
            {"pid": 123},
            project_name="proj",
            lean_wait_handoff=lambda mode, deadline, since: (
                handoffs.append((mode, deadline, since)) or True
            ),
        )

    assert blocked is True
    assert handoffs == [("dependency", None, 1000.0)]
    assert (waiter / "waiting.json").exists()


def test_duration_handoff_requires_thirty_seconds_left_and_blocked(
    tmp_path: Path,
) -> None:
    waiter = _make_waiter(tmp_path)
    handoffs: list[tuple[str, float | None, float]] = []

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.mark_lifecycle_phase"),
        patch("sase.axe.run_agent_wait.release_idle_memory"),
        patch("sase.axe.run_agent_wait.time.time", return_value=1000.0),
        patch("sase.axe.run_agent_wait.time.monotonic", side_effect=[0.0, 31.0]),
    ):
        blocked = wait_for_dependencies(
            [],
            str(waiter),
            "work",
            "20261122010101",
            {"pid": 123},
            duration=90,
            lean_wait_handoff=lambda mode, deadline, since: (
                handoffs.append((mode, deadline, since)) or True
            ),
        )

    assert blocked is True
    assert handoffs == [("duration", 1090.0, 1000.0)]
    assert (waiter / "waiting.json").exists()


def test_lean_release_records_telemetry_and_starts_post_dependency_floor_at_release(
    tmp_path: Path,
) -> None:
    waiter = _make_waiter(tmp_path)
    (waiter / "waiting.json").write_text("{}", encoding="utf-8")
    (waiter / "ready.json").write_text("{}", encoding="utf-8")
    agent_meta = {"pid": 123}
    result = {
        "version": 1,
        "outcome": "released",
        "artifacts_dir": str(waiter),
        "release_source": "runner_fallback",
        "dependencies_satisfied_at": 99.0,
        "released_at": 100.0,
        "killed_at": None,
    }
    deadlines: list[str] = []

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.mark_lifecycle_phase"),
        patch("sase.axe.run_agent_wait.remaining_until", return_value=0.0),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation"
        ),
        patch(
            "sase.axe.run_agent_wait_markers.update_agent_artifact_index_for_marker_mutation"
        ),
        patch(
            "sase.axe.run_agent_wait.set_waiting_until",
            side_effect=lambda _path, deadline: deadlines.append(deadline),
        ),
    ):
        blocked = wait_for_dependencies(
            ["dependency"],
            str(waiter),
            "work",
            "20261122010101",
            agent_meta,
            duration=15,
            lean_wait_result=result,
        )

    saved = json.loads((waiter / "agent_meta.json").read_text(encoding="utf-8"))
    assert blocked is True
    assert deadlines == ["1970-01-01T00:01:55+00:00"]
    assert saved["wait_release_source"] == "runner_fallback"
    assert saved["wait_dependencies_satisfied_at"] == 99.0
    assert saved["wait_release_latency_s"] == 1.0
    assert not (waiter / "waiting.json").exists()
    assert not (waiter / "ready.json").exists()


def test_time_only_lean_release_does_not_repeat_the_completed_wait(
    tmp_path: Path,
) -> None:
    waiter = _make_waiter(tmp_path)
    (waiter / "waiting.json").write_text("{}", encoding="utf-8")
    agent_meta = {"pid": 123}
    result = {
        "version": 1,
        "outcome": "released",
        "artifacts_dir": str(waiter),
        "release_source": "timer",
        "dependencies_satisfied_at": None,
        "released_at": None,
        "killed_at": None,
    }

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.mark_lifecycle_phase"),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation"
        ),
        patch(
            "sase.axe.run_agent_wait_markers.update_agent_artifact_index_for_marker_mutation"
        ),
        patch(
            "sase.axe.run_agent_wait.remaining_until",
            side_effect=AssertionError("time-only wait must not be repeated"),
        ),
    ):
        blocked = wait_for_dependencies(
            [],
            str(waiter),
            "work",
            "20261122010101",
            agent_meta,
            duration=60,
            lean_wait_result=result,
        )

    saved = json.loads((waiter / "agent_meta.json").read_text(encoding="utf-8"))
    assert blocked is True
    assert saved["wait_release_source"] == "timer"
    assert not (waiter / "waiting.json").exists()

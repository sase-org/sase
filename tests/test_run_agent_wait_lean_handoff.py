"""Wait-loop eligibility and refreshed-pass tests for the lean waiter."""

from __future__ import annotations

import json
import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe import run_agent_runner
from sase.axe.run_agent_runner_state import RunnerRunState
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


def test_kill_during_resumed_floor_cleans_markers_without_completing_wait(
    tmp_path: Path,
) -> None:
    waiter = _make_waiter(tmp_path)
    (waiter / "waiting.json").write_text("{}", encoding="utf-8")
    (waiter / "ready.json").write_text("{}", encoding="utf-8")
    result = {
        "version": 1,
        "outcome": "released",
        "artifacts_dir": str(waiter),
        "release_source": "ready_json",
        "dependencies_satisfied_at": 99.0,
        "released_at": 100.0,
        "killed_at": None,
    }
    killed = False

    def kill_after_first_floor_sleep(_seconds: float) -> None:
        nonlocal killed
        killed = True

    with (
        patch("sase.axe.run_agent_wait.record_wait_completed_at") as completed,
        patch("sase.axe.run_agent_wait.was_killed", side_effect=lambda: killed),
        patch("sase.axe.run_agent_wait.mark_lifecycle_phase"),
        patch("sase.axe.run_agent_wait.remaining_until", side_effect=[1.0, 0.0]),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=kill_after_first_floor_sleep,
        ),
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
        patch(
            "sase.axe.run_agent_wait_markers.update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        with pytest.raises(SystemExit) as exc_info:
            wait_for_dependencies(
                ["dependency"],
                str(waiter),
                "work",
                "20261122010101",
                {"pid": 123},
                duration=30,
                lean_wait_result=result,
            )

    assert exc_info.value.code == 128 + signal.SIGTERM
    completed.assert_not_called()
    assert update_index.call_count == 1
    assert not (waiter / "waiting.json").exists()
    assert not (waiter / "ready.json").exists()


def test_floor_kill_exits_before_refresh_repeat_detection_or_launch(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "waiting.json").write_text("{}", encoding="utf-8")
    (artifacts / "ready.json").write_text("{}", encoding="utf-8")
    state = RunnerRunState(
        cl_name="floor-kill",
        project_file=str(tmp_path / "project.sase"),
        prompt_file=str(tmp_path / "prompt.md"),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-20261122010101",
        timestamp="20261122010101",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="proj",
        artifacts_timestamp="20261122010101",
        artifacts_dir=str(artifacts),
        lean_wait_result={
            "version": 1,
            "outcome": "released",
            "artifacts_dir": str(artifacts),
            "release_source": "ready_json",
            "dependencies_satisfied_at": 99.0,
            "released_at": 100.0,
            "killed_at": None,
        },
    )
    info = SimpleNamespace(
        wait_names=["dependency"],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        wait_hoods=[],
        wait_duration=30,
        wait_until=None,
        wait_for_epics_of=None,
        local_macros={"must_not_expand": object()},
        wait_runners=None,
        queue_capacity_multiplier=None,
        wait_priority=None,
        queue_weight=1.0,
        queue_weight_explicit=False,
        hold=None,
    )
    bootstrap = SimpleNamespace(
        info=info,
        agent_meta={"pid": 123, "name": "worker"},
        has_dependency_wait=True,
    )
    killed = False

    def kill_after_floor_sleep(_seconds: float) -> None:
        nonlocal killed
        killed = True

    with (
        patch.object(run_agent_runner, "bootstrap_agent_run", return_value=bootstrap),
        patch.object(run_agent_runner, "was_killed", side_effect=lambda: killed),
        patch("sase.axe.run_agent_wait.was_killed", side_effect=lambda: killed),
        patch("sase.axe.run_agent_wait.mark_lifecycle_phase"),
        patch("sase.axe.run_agent_wait.remaining_until", side_effect=[1.0, 0.0]),
        patch("sase.axe.run_agent_wait.time.sleep", side_effect=kill_after_floor_sleep),
        patch("sase.axe.run_agent_wait.set_waiting_until"),
        patch("sase.axe.run_agent_wait.record_wait_completed_at") as record_completed,
        patch(
            "sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation"
        ),
        patch(
            "sase.axe.run_agent_wait_markers.update_agent_artifact_index_for_marker_mutation"
        ),
        patch.object(run_agent_runner, "refresh_runner_code_after_wait") as refresh,
        patch.object(run_agent_runner, "detect_repeat_stop") as repeat_stop,
        patch.object(run_agent_runner, "expand_deferred_launch_macros") as expand,
        patch.object(run_agent_runner, "launch_agent_run") as launch,
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_agent_runner._run_agent(state)

    assert exc_info.value.code == 128 + signal.SIGTERM
    record_completed.assert_not_called()
    refresh.assert_not_called()
    repeat_stop.assert_not_called()
    expand.assert_not_called()
    launch.assert_not_called()
    assert not (artifacts / "waiting.json").exists()
    assert not (artifacts / "ready.json").exists()

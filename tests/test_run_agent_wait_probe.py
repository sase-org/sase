"""Tests for the lean waiter's one-shot dependency probe script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import sase.axe.run_agent_wait_deps as run_agent_wait_deps
import sase.axe.run_agent_wait_probe as probe
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent


class _Resolution:
    def __init__(self, resolved: bool, satisfied_at: float | None = None) -> None:
        self.resolved = resolved
        self.satisfied_at = satisfied_at

    def __bool__(self) -> bool:
        return self.resolved


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--waiting-path",
        str(tmp_path / "waiting.json"),
        "--artifacts-dir",
        str(tmp_path),
        "--project-name",
        "proj",
        *extra,
    ]


def test_probe_reports_released_with_satisfied_at_as_one_json_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, Any] = {}

    def resolve(waiting_path: Path, **kwargs: Any) -> _Resolution:
        seen.update(kwargs, waiting_path=waiting_path)
        print("resolver progress line")
        return _Resolution(True, 42.5)

    monkeypatch.setattr(
        run_agent_wait_deps, "waiting_marker_dependencies_resolved", resolve
    )

    assert probe.main(_argv(tmp_path)) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"released": True, "satisfied_at": 42.5}
    assert captured.out.count("\n") == 1
    # The resolver's own prints never pollute the result stream.
    assert "resolver progress line" in captured.err
    assert seen == {
        "waiting_path": tmp_path / "waiting.json",
        "project_name": "proj",
        "artifacts_dir": str(tmp_path),
    }


def test_probe_reports_not_released_with_a_null_satisfied_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        run_agent_wait_deps,
        "waiting_marker_dependencies_resolved",
        lambda *args, **kwargs: _Resolution(False, 9.0),
    )

    assert probe.main(_argv(tmp_path)) == 0

    assert json.loads(capsys.readouterr().out) == {
        "released": False,
        "satisfied_at": None,
    }


def test_probe_released_without_satisfied_at_reports_null(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        run_agent_wait_deps,
        "waiting_marker_dependencies_resolved",
        lambda *args, **kwargs: _Resolution(True, None),
    )

    assert probe.main(_argv(tmp_path)) == 0

    assert json.loads(capsys.readouterr().out) == {
        "released": True,
        "satisfied_at": None,
    }


def test_probe_internal_error_exits_nonzero_with_no_result_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(*args: Any, **kwargs: Any) -> _Resolution:
        raise RuntimeError("resolver blew up")

    monkeypatch.setattr(
        run_agent_wait_deps, "waiting_marker_dependencies_resolved", explode
    )

    assert probe.main(_argv(tmp_path)) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "resolver blew up" in captured.err


def test_bead_sync_hint_runs_before_the_resolution_only_when_asked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        run_agent_wait_deps,
        "mark_bead_wait_sync_hint",
        lambda project: calls.append(f"hint:{project}"),
    )

    def resolve(*args: Any, **kwargs: Any) -> _Resolution:
        calls.append("resolve")
        return _Resolution(False)

    monkeypatch.setattr(
        run_agent_wait_deps, "waiting_marker_dependencies_resolved", resolve
    )

    assert probe.main(_argv(tmp_path)) == 0
    assert calls == ["resolve"]

    calls.clear()
    assert probe.main(_argv(tmp_path, "--bead-sync-hint")) == 0
    assert calls == ["hint:proj", "resolve"]
    capsys.readouterr()


def _run_probe_by_path(home: Path, waiter_dir: Path) -> dict[str, Any]:
    # The pytest state guard refuses real-state access from marked processes;
    # this child reads a synthetic HOME, so it must not look like a pytest run.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST", "SASE_PYTEST")) and key != "SASE_HOME"
    }
    env["HOME"] = str(home)
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(probe.__file__ or "")),
            "--waiting-path",
            str(waiter_dir / "waiting.json"),
            "--artifacts-dir",
            str(waiter_dir),
            "--project-name",
            "proj",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.strip().splitlines()
    assert len(lines) == 1, completed.stdout
    result: dict[str, Any] = json.loads(lines[0])
    return result


def test_real_probe_by_path_releases_a_finished_named_dependency(
    tmp_path: Path,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path, "proj", "20260506010101", "foo", done=True, outcome="completed"
    )

    result = _run_probe_by_path(tmp_path, waiter_dir)

    assert result["released"] is True
    assert result["satisfied_at"] is None or isinstance(result["satisfied_at"], float)


def test_real_probe_by_path_keeps_an_unfinished_dependency_parked(
    tmp_path: Path,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(tmp_path, "proj", "20260506010101", "foo")

    assert _run_probe_by_path(tmp_path, waiter_dir) == {
        "released": False,
        "satisfied_at": None,
    }

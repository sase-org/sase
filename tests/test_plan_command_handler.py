"""Tests for ``sase plan`` command handler."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main import plan_command_handler
from tests.conftest import redirect_sase_home


def _make_artifacts_dir(sase_home: Path) -> Path:
    """Create a realistic artifacts dir layout and return the timestamp dir."""
    artifacts_dir = (
        sase_home
        / "projects"
        / "demo"
        / "artifacts"
        / "workflow-plan"
        / "20260428120000"
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def _invoke_plan(plan_file: Path) -> None:
    """Invoke ``handle_plan_command`` swallowing the trailing ``SystemExit``."""
    with pytest.raises(SystemExit):
        plan_command_handler.handle_plan_command(str(plan_file))


def test_plan_command_writes_refresh_pulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sase plan` pulses ``.ace_refresh_pulse`` in the watched ``artifacts/`` dir."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)
    project_artifacts_root = artifacts_dir.parents[1]

    plan_file = tmp_path / "my_plan.md"
    plan_file.write_text("# Plan\n\nbody\n", encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    pulse_path = project_artifacts_root / ".ace_refresh_pulse"
    assert not pulse_path.exists()

    with (
        patch.object(plan_command_handler, "kill_agent_runner_group") as kill_mock,
        patch(
            "sase.gemini_wrapper.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        kill_mock.side_effect = SystemExit(0)
        _invoke_plan(plan_file)

    assert pulse_path.is_file()
    assert pulse_path.parent == project_artifacts_root
    # The pulse file lives directly inside the watched ``artifacts/`` dir, so
    # it is a direct child of a path the ACE inotify watcher actually sees.


def test_plan_command_pulse_mtime_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeat invocations rewrite the pulse so its mtime moves forward."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)
    pulse_path = artifacts_dir.parents[1] / ".ace_refresh_pulse"

    plan_file = tmp_path / "my_plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch.object(plan_command_handler, "kill_agent_runner_group") as kill_mock,
        patch(
            "sase.gemini_wrapper.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        kill_mock.side_effect = SystemExit(0)

        _invoke_plan(plan_file)
        first_mtime = pulse_path.stat().st_mtime_ns

        # Force the filesystem clock to advance so mtime resolution differences
        # don't cause flakes on filesystems with coarse mtime granularity.
        time.sleep(0.01)
        _invoke_plan(plan_file)
        second_mtime = pulse_path.stat().st_mtime_ns

    assert second_mtime > first_mtime

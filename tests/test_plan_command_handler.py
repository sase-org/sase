"""Tests for ``sase plan`` command handlers."""

from __future__ import annotations

import argparse
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
    """Invoke ``handle_plan_propose_command`` swallowing ``SystemExit``."""
    with pytest.raises(SystemExit):
        plan_command_handler.handle_plan_propose_command(str(plan_file))


def test_plan_command_dispatches_propose() -> None:
    """``sase plan propose`` routes to the proposal handler."""
    args = argparse.Namespace(plan_subcommand="propose", plan_file="plan.md")

    with (
        patch.object(
            plan_command_handler,
            "handle_plan_propose_command",
            side_effect=SystemExit(0),
        ) as propose_mock,
        pytest.raises(SystemExit) as exc_info,
    ):
        plan_command_handler.handle_plan_command(args)

    assert exc_info.value.code == 0
    propose_mock.assert_called_once_with("plan.md")


def test_plan_command_writes_refresh_pulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sase plan propose`` pulses ``.ace_refresh_pulse`` in ``artifacts/``."""
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
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
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
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        kill_mock.side_effect = SystemExit(0)

        _invoke_plan(plan_file)
        first_mtime = pulse_path.stat().st_mtime_ns

        # The first invocation consumes the scratch plan, so recreate it before
        # proposing again.
        plan_file.write_text("# Plan\n", encoding="utf-8")

        # Force the filesystem clock to advance so mtime resolution differences
        # don't cause flakes on filesystems with coarse mtime granularity.
        time.sleep(0.01)
        _invoke_plan(plan_file)
        second_mtime = pulse_path.stat().st_mtime_ns

    assert second_mtime > first_mtime


def test_plan_command_moves_source_into_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sase plan propose`` archives the formatted plan and consumes the source."""
    import json

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)

    plan_file = tmp_path / "sase_plan_feature.md"
    plan_file.write_text("# Plan\n\nbody\n", encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    formatted = "# Plan\n\nformatted body\n"
    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw.replace("body", "formatted body"),
        ),
    ):
        kill_mock.side_effect = SystemExit(0)
        _invoke_plan(plan_file)

    # The scratch source file is consumed by the move into the archive.
    assert not plan_file.exists()

    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    # ``plan_file`` points at the durable archive copy, which exists on disk.
    archived_path = Path(marker["plan_file"])
    assert archived_path.is_file()
    assert archived_path.parent.parent == sase_home / "plans"
    assert archived_path.name == "feature.md"  # "sase_plan_" prefix stripped
    # The archive holds the prettier-formatted content, not the raw source.
    assert archived_path.read_text(encoding="utf-8") == formatted
    # ``original_file`` is retained as provenance even though it no longer exists.
    assert marker["original_file"] == str(plan_file.resolve())

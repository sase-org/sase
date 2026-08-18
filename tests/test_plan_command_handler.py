"""Core tests for ``sase plan`` command handlers."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main import plan_command_handler
from tests.conftest import redirect_sase_home
from tests.plan_command_handler_helpers import (
    VALID_EPIC,
    VALID_TALE,
    clear_bead_work_association_env,
    invoke_plan as _invoke_plan,
    make_artifacts_dir as _make_artifacts_dir,
)


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_bead_work_association_env(monkeypatch)


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
    plan_file.write_text(VALID_TALE, encoding="utf-8")

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
        assert _invoke_plan(plan_file) == 0

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
    plan_file.write_text(VALID_TALE, encoding="utf-8")

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

        assert _invoke_plan(plan_file) == 0
        first_mtime = pulse_path.stat().st_mtime_ns

        # The runner consumes the pending marker before the next turn. A
        # second propose with that marker still on disk is a second hand-off
        # from one turn and is refused.
        (artifacts_dir / ".sase_plan_pending").unlink()

        # The first invocation consumes the scratch plan, so recreate it before
        # proposing again.
        plan_file.write_text(VALID_TALE, encoding="utf-8")

        # Force the filesystem clock to advance so mtime resolution differences
        # don't cause flakes on filesystems with coarse mtime granularity.
        time.sleep(0.01)  # sase-test-wait: separates pulse mtimes
        assert _invoke_plan(plan_file) == 0
        second_mtime = pulse_path.stat().st_mtime_ns

    assert second_mtime > first_mtime


def test_plan_command_moves_source_into_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sase plan propose`` archives the formatted plan and consumes the source."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    artifacts_dir = _make_artifacts_dir(sase_home)

    plan_file = tmp_path / "sase_plan_feature.md"
    plan_file.write_text(VALID_TALE, encoding="utf-8")

    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    formatted = VALID_TALE.replace("body", "formatted body")
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
        assert _invoke_plan(plan_file) == 0

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


def test_plan_command_accepts_valid_epic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An authored epic is validated against the epic schema before queuing."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "epic.md"
    plan_file.write_text(VALID_EPIC, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ) as kill_mock,
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda raw: raw,
        ),
    ):
        assert _invoke_plan(plan_file) == 0

    kill_mock.assert_called_once_with(str(artifacts_dir))
    assert (artifacts_dir / ".sase_plan_pending").is_file()


def test_plan_command_rejects_legacy_sizeless_tale_in_authoring_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase plan propose`` keeps authoring strict for new tale plans."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    content = VALID_TALE.replace("size: small\n", "")
    plan_file = tmp_path / "legacy-tale.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch("sase.main.plan_propose_handler.kill_agent_runner_group") as kill_mock,
        patch("sase.file_references.format_with_prettier") as format_mock,
    ):
        assert _invoke_plan(plan_file) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error [tale-size-missing]" in captured.err.lower()
    assert "Expected tale frontmatter schema" in captured.err
    assert plan_file.read_text(encoding="utf-8") == content
    assert not (artifacts_dir / ".sase_plan_pending").exists()
    format_mock.assert_not_called()
    kill_mock.assert_not_called()


@pytest.mark.parametrize(
    ("content", "auto_action", "expected_tier", "expected_code"),
    [
        ("# Plan\n\nbody\n", None, "tale", "frontmatter-missing"),
        (
            """---
tier: tale
goal: '   '
---
# Plan
""",
            None,
            "tale",
            "value-empty",
        ),
        (
            """---
tier: epic
title: Empty epic
goal: Deliver it
phases: []
---
# Plan
""",
            None,
            "epic",
            "phases-empty",
        ),
        (VALID_TALE, "epic", "tale", "invalid-auto-argument"),
        (VALID_EPIC, "tale", "epic", "invalid-auto-argument"),
    ],
)
def test_plan_command_rejects_invalid_or_auto_mismatched_plan_without_side_effects(
    content: str,
    auto_action: str | None,
    expected_tier: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed gate leaves the source and proposal queue untouched."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "invalid.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    if auto_action is not None:
        monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE_PLAN_ACTION", auto_action)

    with (
        patch("sase.main.plan_propose_handler.kill_agent_runner_group") as kill_mock,
        patch("sase.file_references.format_with_prettier") as format_mock,
    ):
        assert _invoke_plan(plan_file) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"error [{expected_code}]" in captured.err.lower()
    if expected_code == "invalid-auto-argument":
        assert f"conflicts with the authored {expected_tier} plan tier" in captured.err
    else:
        assert f"Expected {expected_tier} frontmatter schema" in captured.err
        assert "Validation failed" in captured.err
    assert plan_file.read_text(encoding="utf-8") == content
    assert not (artifacts_dir / ".sase_plan_pending").exists()
    assert not (artifacts_dir.parents[1] / ".ace_refresh_pulse").exists()
    format_mock.assert_not_called()
    kill_mock.assert_not_called()

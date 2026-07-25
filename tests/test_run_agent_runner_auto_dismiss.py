"""Tests for run-agent runner auto-dismiss persistence."""

from __future__ import annotations

import signal
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_runner_lifecycle import auto_dismiss_completed_agent
from sase.axe.run_agent_runner_signals import (
    install_workspace_release_sigterm_handler,
)
from sase.axe.runner_signals import reset_killed, was_killed


def test_auto_dismiss_completed_agent_syncs_dismissed_projection() -> None:
    dismissed: set[tuple[AgentType, str, str | None]] = set()

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents", return_value=dismissed
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as save,
        patch(
            "sase.axe.run_agent_runner_lifecycle.sync_dismissed_agent_artifact_index"
        ) as sync_index,
    ):
        auto_dismiss_completed_agent("feature_x", "20260510130000")

    identities = {
        (AgentType.RUNNING, "feature_x", "20260510130000"),
        (AgentType.WORKFLOW, "feature_x", "20260510130000"),
    }
    assert dismissed == identities
    save.assert_called_once_with(dismissed)
    sync_index.assert_called_once_with(dismissed, added=identities)


def test_workspace_release_sigterm_handler_releases_claim(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    project_file = "/tmp/.sase/projects/sase/sase.sase"
    with patch("sase.axe.runner_signals.signal.signal") as signal_handler:
        install_workspace_release_sigterm_handler(
            project_file=project_file,
            workspace_num=10,
            workflow_name="ace(run)-260101_120000",
            cl_name="sase",
            is_home_mode=False,
        )
        captured_handler = signal_handler.call_args[0][1]

    with (
        patch("sase.running_field.release_workspace") as release,
        patch("sase.axe.runner_signals.sys.exit") as exit_mock,
    ):
        captured_handler(signal.SIGTERM, None)

    release.assert_called_once_with(
        project_file,
        10,
        "ace(run)-260101_120000",
        "sase",
    )
    exit_mock.assert_not_called()
    assert was_killed() is True
    reset_killed()


def test_workspace_release_sigterm_handler_skips_plan_handoff(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / ".sase_plan_pending").write_text("{}", encoding="utf-8")

    with patch("sase.axe.runner_signals.signal.signal") as signal_handler:
        install_workspace_release_sigterm_handler(
            project_file="/tmp/.sase/projects/sase/sase.sase",
            workspace_num=10,
            workflow_name="ace(run)-260101_120000",
            cl_name="sase",
            is_home_mode=False,
        )
        captured_handler = signal_handler.call_args[0][1]

    with (
        patch("sase.running_field.release_workspace") as release,
        patch("sase.axe.runner_signals.sys.exit") as exit_mock,
    ):
        captured_handler(signal.SIGTERM, None)

    release.assert_not_called()
    exit_mock.assert_not_called()
    assert was_killed() is True
    reset_killed()


def test_workspace_release_sigterm_handler_skips_question_handoff(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / ".sase_questions_pending").write_text("{}", encoding="utf-8")

    with patch("sase.axe.runner_signals.signal.signal") as signal_handler:
        install_workspace_release_sigterm_handler(
            project_file="/tmp/.sase/projects/sase/sase.sase",
            workspace_num=10,
            workflow_name="ace(run)-260101_120000",
            cl_name="sase",
            is_home_mode=False,
        )
        captured_handler = signal_handler.call_args[0][1]

    with (
        patch("sase.running_field.release_workspace") as release,
        patch("sase.axe.runner_signals.sys.exit") as exit_mock,
    ):
        captured_handler(signal.SIGTERM, None)

    release.assert_not_called()
    exit_mock.assert_not_called()
    assert was_killed() is True
    reset_killed()


def test_workspace_release_sigterm_handler_uses_artifacts_fallback(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    (tmp_path / ".sase_plan_pending").write_text("{}", encoding="utf-8")

    with patch("sase.axe.runner_signals.signal.signal") as signal_handler:
        install_workspace_release_sigterm_handler(
            project_file="/tmp/.sase/projects/sase/sase.sase",
            workspace_num=10,
            workflow_name="ace(run)-260101_120000",
            cl_name="sase",
            is_home_mode=False,
            artifacts_dir_getter=lambda: str(tmp_path),
        )
        captured_handler = signal_handler.call_args[0][1]

    with (
        patch("sase.running_field.release_workspace") as release,
        patch("sase.axe.runner_signals.sys.exit") as exit_mock,
    ):
        captured_handler(signal.SIGTERM, None)

    release.assert_not_called()
    exit_mock.assert_not_called()
    assert was_killed() is True
    reset_killed()

"""Tests for run-agent runner auto-dismiss persistence."""

from __future__ import annotations

import signal
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.agent._user_kill_intent import write_user_kill_intent
from sase.axe.run_agent_runner_lifecycle import auto_dismiss_completed_agent
from sase.axe.run_agent_runner_signals import (
    install_workspace_release_sigterm_handler,
)
from sase.axe.runner_signals import reset_killed, was_killed
from sase.running_field import WorkspaceClaim


def test_auto_dismiss_completed_agent_syncs_dismissed_projection() -> None:
    identities = {
        (AgentType.RUNNING, "feature_x", "20260510130000"),
        (AgentType.WORKFLOW, "feature_x", "20260510130000"),
    }
    on_disk = identities | {(AgentType.RUNNING, "other", "20260510120000")}

    with (
        patch(
            "sase.ace.dismissed_agents.add_dismissed_agents", return_value=on_disk
        ) as add,
        patch(
            "sase.axe.run_agent_runner_lifecycle.sync_dismissed_agent_artifact_index"
        ) as sync_index,
    ):
        auto_dismiss_completed_agent("feature_x", "20260510130000")

    # Only this run's identities are merged; the index syncs what is on disk.
    add.assert_called_once_with(identities)
    sync_index.assert_called_once_with(on_disk, added=identities)


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


def test_workspace_release_sigterm_handler_skips_hijack_intent(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    write_user_kill_intent(
        tmp_path,
        pid=9,
        source="test",
        mode="hijack",
        hijack_id="h-1",
    )

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


def test_workspace_release_sigterm_handler_releases_plain_user_kill(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    write_user_kill_intent(tmp_path, pid=9, source="test")
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


def test_workspace_release_sigterm_handler_releases_despite_pending_markers(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / ".sase_plan_pending").write_text("{}", encoding="utf-8")
    (tmp_path / ".sase_pipe_pending").write_text("{}", encoding="utf-8")
    (tmp_path / ".sase_questions_pending").write_text("{}", encoding="utf-8")
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


def test_workspace_release_sigterm_handler_skips_staged_handoff(
    tmp_path, monkeypatch
) -> None:
    from sase.agent.staged_handoff import build_plan_staged_record, write_staged_handoff

    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT", "1")
    write_staged_handoff(
        build_plan_staged_record(
            plan_file="/tmp/plan.md",
            original_file="/tmp/plan.md",
            dirty_obligations_at_stage=[],
            created_at="2026-10-28T12:00:00Z",
        ),
        artifacts_dir=str(tmp_path),
    )

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


def test_workspace_release_sigterm_handler_skips_monitor_handoff(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / ".sase_monitor_pending").write_text("{}", encoding="utf-8")

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
        patch(
            "sase.running_field.get_claimed_workspaces",
            return_value=[
                WorkspaceClaim(
                    workspace_num=10,
                    workflow="ace-monitor",
                    cl_name="sase",
                    pid=12345,
                )
            ],
        ),
        patch("sase.ace.hooks.processes.is_process_running", return_value=True),
        patch("sase.running_field.release_workspace") as release,
        patch("sase.axe.runner_signals.sys.exit") as exit_mock,
    ):
        captured_handler(signal.SIGTERM, None)

    release.assert_not_called()
    exit_mock.assert_not_called()
    assert was_killed() is True
    reset_killed()


def test_workspace_release_sigterm_handler_releases_failed_monitor_handoff(
    tmp_path, monkeypatch
) -> None:
    reset_killed()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / ".sase_monitor_pending").write_text("{}", encoding="utf-8")
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
        patch("sase.running_field.get_claimed_workspaces", return_value=[]),
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


def test_workspace_release_sigterm_handler_uses_artifacts_fallback(
    tmp_path, monkeypatch
) -> None:
    from sase.agent.staged_handoff import build_plan_staged_record, write_staged_handoff

    reset_killed()
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setenv("SASE_AGENT", "1")
    write_staged_handoff(
        build_plan_staged_record(
            plan_file="/tmp/plan.md",
            original_file="/tmp/plan.md",
            dirty_obligations_at_stage=[],
            created_at="2026-10-28T12:00:00Z",
        ),
        artifacts_dir=str(tmp_path),
    )

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

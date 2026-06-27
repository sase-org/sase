"""Tests for run-agent runner auto-dismiss persistence."""

from __future__ import annotations

import signal
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_runner import (
    _auto_dismiss_completed_agent,
    _install_workspace_release_sigterm_handler,
)
from sase.axe.runner_utils import reset_killed


def test_auto_dismiss_completed_agent_syncs_dismissed_projection() -> None:
    dismissed: set[tuple[AgentType, str, str | None]] = set()

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agents", return_value=dismissed
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as save,
        patch(
            "sase.axe.run_agent_runner.sync_dismissed_agent_artifact_index"
        ) as sync_index,
    ):
        _auto_dismiss_completed_agent("feature_x", "20260510130000")

    identities = {
        (AgentType.RUNNING, "feature_x", "20260510130000"),
        (AgentType.WORKFLOW, "feature_x", "20260510130000"),
    }
    assert dismissed == identities
    save.assert_called_once_with(dismissed)
    sync_index.assert_called_once_with(dismissed, added=identities)


def test_workspace_release_sigterm_handler_releases_claim() -> None:
    with patch("sase.axe.runner_utils.signal.signal") as signal_handler:
        _install_workspace_release_sigterm_handler(
            project_file="/tmp/.sase/projects/sase/sase.sase",
            workspace_num=10,
            workflow_name="ace(run)-260101_120000",
            cl_name="sase",
            is_home_mode=False,
        )
        captured_handler = signal_handler.call_args[0][1]

    with (
        patch("sase.running_field.release_workspace") as release,
        patch("sase.axe.runner_utils.sys.exit"),
    ):
        captured_handler(signal.SIGTERM, None)

    release.assert_called_once_with(
        "/tmp/.sase/projects/sase/sase.sase",
        10,
        "ace(run)-260101_120000",
        "sase",
    )
    reset_killed()

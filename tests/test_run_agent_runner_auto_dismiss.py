"""Tests for run-agent runner auto-dismiss persistence."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_runner import _auto_dismiss_completed_agent


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

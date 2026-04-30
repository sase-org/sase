"""Tests for run_agent_runner's completion-notification helper.

Specifically guards that hidden agents (lumberjack chops, %hidden,
SASE_AGENT_AUTO_DISMISS) forward ``silent=True`` to
``notify_workflow_complete`` so they don't ping Telegram / bell / unread
count for runs the user never asked to see.
"""

from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_finalize import (
    classify_exec_success,
    send_completion_notification,
)


@pytest.fixture
def base_kwargs(tmp_path):
    """Minimal valid args; tests override only the bits they care about."""
    return {
        "cl_name": "test-cl",
        "artifacts_timestamp": "20260425232621",
        "workflow_name": "pylimit_split",
        "success": True,
        "agent_hidden": False,
        "agent_name": None,
        "agent_model": "opus",
        "agent_llm_provider": "claude",
        "error_summary": None,
        "error_report_path": None,
        "saved_path": None,
        "diff_path": None,
        "output_path": str(tmp_path / "output.log"),
        "step_output": None,
        "prompt": "#gh:sase #!sase/pylimit_split %approve",
    }


def test_hidden_agent_forwards_silent_true(base_kwargs):
    base_kwargs["agent_hidden"] = True
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    assert mock_notify.call_args.kwargs["silent"] is True


def test_visible_agent_forwards_silent_false(base_kwargs):
    base_kwargs["agent_hidden"] = False
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    assert mock_notify.call_args.kwargs["silent"] is False


def test_hidden_agent_failure_still_silent(base_kwargs):
    """Hidden runs are silent for failures too — matches sibling runners."""
    base_kwargs["agent_hidden"] = True
    base_kwargs["success"] = False
    base_kwargs["error_summary"] = "boom"
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["silent"] is True
    assert mock_notify.call_args.kwargs["success"] is False


def test_plan_rejected_suppresses_completion_notification(base_kwargs):
    base_kwargs["success"] = True
    base_kwargs["outcome"] = "plan_rejected"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    mock_notify.assert_not_called()


def test_plan_rejected_classifies_as_runner_success():
    assert classify_exec_success(success=False, outcome="plan_rejected") is True


def test_real_failure_stays_runner_failure():
    assert classify_exec_success(success=False, outcome="killed") is False

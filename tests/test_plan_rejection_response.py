"""Test that TUI rejection-without-feedback writes plan_response.json."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.plan_approval_modal import PlanApprovalResult
from sase.notifications import Notification


def test_reject_without_feedback_writes_plan_response(tmp_path: Path) -> None:
    """Rejecting a plan without feedback should write plan_response.json.

    This ensures external watchers (e.g. Telegram) can detect the rejection
    and dismiss their interactive buttons.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    request_file = response_dir / "plan_request.json"
    request_file.write_text("{}")

    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan")

    notification = Notification(
        id="test-notif",
        timestamp="2026-03-29T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"response_dir": str(response_dir)},
        files=[str(plan_file)],
    )

    app = MagicMock()
    app._agent_status_overrides = {}
    app._agent_pre_question_status = {}

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
        return_value=None,
    ):
        handle_plan_approval(app, notification)

    # Capture the on_dismiss callback passed to push_screen
    assert app.push_screen.called
    on_dismiss = app.push_screen.call_args[0][1]

    # Simulate reject without feedback
    with patch("sase.notifications.mark_dismissed"):
        on_dismiss(PlanApprovalResult(action="reject", feedback=None))

    # Verify plan_response.json was written with reject action
    plan_response_path = response_dir / "plan_response.json"
    assert plan_response_path.exists()
    data = json.loads(plan_response_path.read_text())
    assert data == {"action": "reject"}


def test_approve_commit_only_writes_options_and_sets_committed_status(
    tmp_path: Path,
) -> None:
    """Approve-with-options commit-only should keep committed status semantics."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}")

    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan")

    notification = Notification(
        id="test-notif",
        timestamp="2026-03-29T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"response_dir": str(response_dir)},
        files=[str(plan_file)],
    )

    app = MagicMock()
    app._agent_status_overrides = {}
    app._agent_pre_question_status = {}
    app._load_agents = MagicMock()

    agent = MagicMock()
    agent.identity = "agent-1"

    from sase.ace.tui.actions.agents._notification_modals import handle_plan_approval

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
            return_value=agent,
        ),
        patch("sase.notifications.mark_dismissed"),
        patch(
            "sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"
        ) as mock_persist,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(
            PlanApprovalResult(
                action="approve",
                commit_plan=True,
                run_coder=False,
            )
        )

    data = json.loads((response_dir / "plan_response.json").read_text())
    assert data == {"action": "approve", "commit_plan": True, "run_coder": False}
    assert app._agent_status_overrides["agent-1"] == "PLAN COMMITTED"
    mock_persist.assert_called_once_with(agent, action="commit")


def test_approve_with_prompt_extra_writes_prompt_and_sets_approved_status(
    tmp_path: Path,
) -> None:
    """Approve-with-options should include coder_prompt_extra in response JSON."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}")

    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan")

    notification = Notification(
        id="test-notif",
        timestamp="2026-03-29T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"response_dir": str(response_dir)},
        files=[str(plan_file)],
    )

    app = MagicMock()
    app._agent_status_overrides = {}
    app._agent_pre_question_status = {}
    app._load_agents = MagicMock()

    agent = MagicMock()
    agent.identity = "agent-1"

    from sase.ace.tui.actions.agents._notification_modals import handle_plan_approval

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
            return_value=agent,
        ),
        patch("sase.notifications.mark_dismissed"),
        patch(
            "sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"
        ) as mock_persist,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(
            PlanApprovalResult(
                action="approve",
                commit_plan=True,
                run_coder=True,
                coder_prompt_extra="#foo\nbar",
            )
        )

    data = json.loads((response_dir / "plan_response.json").read_text())
    assert data == {
        "action": "approve",
        "commit_plan": True,
        "run_coder": True,
        "coder_prompt_extra": "#foo\nbar",
    }
    assert app._agent_status_overrides["agent-1"] == "PLAN APPROVED"
    mock_persist.assert_called_once_with(agent, action="approve")

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


def _make_approval_app_and_notification(tmp_path: Path) -> tuple:
    """Create mock app, notification, and response_dir for approval tests."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}")

    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan")

    notification = Notification(
        id="test-notif",
        timestamp="2026-03-31T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"response_dir": str(response_dir)},
        files=[str(plan_file)],
    )

    mock_agent = MagicMock()
    mock_agent.identity = "test-agent-identity"

    app = MagicMock()
    app._agent_status_overrides = {}
    app._agent_pre_question_status = {}

    return app, notification, response_dir, mock_agent


def test_approve_commit_only_writes_options_and_sets_committed_status(
    tmp_path: Path,
) -> None:
    """Approve with commit_plan=True, run_coder=False writes options and sets PLAN COMMITTED."""
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
        return_value=mock_agent,
    ):
        handle_plan_approval(app, notification)

        on_dismiss = app.push_screen.call_args[0][1]

        with (
            patch("sase.notifications.mark_dismissed"),
            patch(
                "sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"
            ),
        ):
            on_dismiss(
                PlanApprovalResult(action="approve", commit_plan=True, run_coder=False)
            )

    plan_response_path = response_dir / "plan_response.json"
    assert plan_response_path.exists()
    data = json.loads(plan_response_path.read_text())
    assert data["commit_plan"] is True
    assert data["run_coder"] is False
    assert app._agent_status_overrides[mock_agent.identity] == "PLAN COMMITTED"


def test_approve_with_prompt_writes_prompt_and_sets_approved_status(
    tmp_path: Path,
) -> None:
    """Approve with coder_prompt writes prompt in response and sets PLAN APPROVED."""
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
        return_value=mock_agent,
    ):
        handle_plan_approval(app, notification)

        on_dismiss = app.push_screen.call_args[0][1]

        with (
            patch("sase.notifications.mark_dismissed"),
            patch(
                "sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"
            ),
        ):
            on_dismiss(
                PlanApprovalResult(
                    action="approve",
                    run_coder=True,
                    coder_prompt="#review+",
                )
            )

    plan_response_path = response_dir / "plan_response.json"
    assert plan_response_path.exists()
    data = json.loads(plan_response_path.read_text())
    assert data["coder_prompt"] == "#review+"
    assert app._agent_status_overrides[mock_agent.identity] == "PLAN APPROVED"

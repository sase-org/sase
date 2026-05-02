"""Test that TUI rejection-without-feedback writes plan_response.json."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalResult
from sase.ace.tui.modals.user_question_modal import (
    UserQuestionResult,
    _QuestionAnswer,
)
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


def test_approve_writes_response_before_archiving_plan(tmp_path: Path) -> None:
    """The agent-unblocking response write happens before slow plan copy work."""
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    app._agents_with_children = [mock_agent]
    app.run_worker.side_effect = lambda work, thread=True: work()
    app.call_from_thread.side_effect = lambda callback: callback()

    plan_response_path = response_dir / "plan_response.json"

    def archive_side_effect(notification: object, action: str = "approve") -> None:
        assert plan_response_path.exists()
        data = json.loads(plan_response_path.read_text())
        assert data["action"] == "approve"
        assert action == "approve"
        assert app._agent_status_overrides[mock_agent.identity] == "PLAN APPROVED"

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch("sase.notifications.mark_dismissed"),
        patch("sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"),
        patch(
            "sase.ace.tui.actions.agents._notification_modals._archive_plan_for_approval",
            side_effect=archive_side_effect,
        ) as archive_plan,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(PlanApprovalResult(action="approve"))

    archive_plan.assert_called_once()


def test_legend_writes_response_and_sets_status(tmp_path: Path) -> None:
    """Legend approval writes the action, persists metadata, and sets LEGEND APPROVED."""
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    app.run_worker.side_effect = lambda work, thread=True: work()
    app.call_from_thread.side_effect = lambda callback: callback()

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
            ) as persist_plan_approved,
            patch(
                "sase.ace.tui.actions.agents._notification_modals._archive_plan_for_approval",
                return_value=None,
            ) as archive_plan,
        ):
            on_dismiss(PlanApprovalResult(action="legend"))

    data = json.loads((response_dir / "plan_response.json").read_text())
    assert data["action"] == "legend"
    assert app._agent_status_overrides[mock_agent.identity] == "LEGEND APPROVED"
    persist_plan_approved.assert_called_once_with(mock_agent, action="legend")
    archive_plan.assert_called_once()
    assert archive_plan.call_args.args[1] == "legend"


def test_approve_uses_cached_refresh_instead_of_sync_load(tmp_path: Path) -> None:
    """Fast-path status refresh should avoid a synchronous full agent load."""
    app, notification, _response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    app._agents_with_children = [mock_agent]
    app.run_worker.side_effect = lambda work, thread=True: work()
    app.call_from_thread.side_effect = lambda callback: callback()

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch("sase.notifications.mark_dismissed"),
        patch("sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"),
        patch(
            "sase.ace.tui.actions.agents._notification_modals._archive_plan_for_approval",
            return_value=None,
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(PlanApprovalResult(action="approve"))

    app._refilter_agents.assert_called_once()
    app._load_agents.assert_not_called()


def test_commit_only_copies_saved_plan_path_after_background_work(
    tmp_path: Path,
) -> None:
    """Commit-only approval still reports the archived path after worker completion."""
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    app._agents_with_children = [mock_agent]
    app.run_worker.side_effect = lambda work, thread=True: work()
    app.call_from_thread.side_effect = lambda callback: callback()
    saved_plan_path = str(Path.home() / "workspace" / ".sase" / "plans" / "plan.md")

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch("sase.notifications.mark_dismissed"),
        patch("sase.ace.tui.actions.agents._notification_modals.persist_plan_approved"),
        patch(
            "sase.ace.tui.actions.agents._notification_modals._archive_plan_for_approval",
            return_value=saved_plan_path,
        ),
        patch(
            "sase.ace.tui.actions.clipboard.copy_to_system_clipboard"
        ) as copy_to_clipboard,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(
            PlanApprovalResult(action="approve", commit_plan=True, run_coder=False)
        )

    assert app._agent_status_overrides[mock_agent.identity] == "PLAN COMMITTED"
    copy_to_clipboard.assert_called_once_with("~/workspace/.sase/plans/plan.md")
    app._refresh_notification_count.assert_called_once()
    app._schedule_agents_async_refresh.assert_called_once()
    data = json.loads((response_dir / "plan_response.json").read_text())
    assert data["saved_plan_path"] == saved_plan_path


def test_user_question_response_dismisses_notification_and_restores_status(
    tmp_path: Path,
) -> None:
    """Answering a question writes the response and dismisses the source notification."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps({"questions": [{"question": "Pick one"}]})
    )

    notification = Notification(
        id="question-notif",
        timestamp="2026-04-25T12:00:00-04:00",
        sender="test",
        action="UserQuestion",
        action_data={
            "response_dir": str(response_dir),
            "agent_cl_name": "my_cl",
            "agent_timestamp": "20260425120000",
        },
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260425120000",
    )
    app = MagicMock()
    app._agents = [agent]
    app._agent_status_overrides = {agent.identity: "QUESTION"}
    app._agent_pre_question_status = {agent.identity: "PLAN APPROVED"}

    from sase.ace.tui.actions.agents._notification_modals import handle_user_question

    assert handle_user_question(app, notification) is True
    on_dismiss = app.push_screen.call_args[0][1]

    with patch("sase.notifications.mark_dismissed") as mark_dismissed:
        on_dismiss(
            UserQuestionResult(
                answers=[
                    _QuestionAnswer(
                        question="Pick one",
                        selected=["A"],
                        custom_feedback="Use A",
                    )
                ],
                global_note="thanks",
            )
        )

    response_data = json.loads((response_dir / "question_response.json").read_text())
    assert response_data == {
        "answers": [
            {
                "question": "Pick one",
                "selected": ["A"],
                "custom_feedback": "Use A",
            }
        ],
        "global_note": "thanks",
    }
    mark_dismissed.assert_called_once_with("question-notif")
    assert app._agent_status_overrides[agent.identity] == "PLAN APPROVED"
    assert agent.identity not in app._agent_pre_question_status
    app._load_agents.assert_called_once()

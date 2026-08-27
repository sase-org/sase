"""Tests for TUI plan approval response handling."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.ace.tui.modals.plan_approval_results import (
    PlanApprovalResult,
    plan_approval_result_for_choice,
)
from sase.notifications import Notification
from tests._plan_approval_tui_helpers import make_approval_app_and_notification
from tests.plan_validation_helpers import VALID_TALE_PLAN


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
    plan_file.write_text(VALID_TALE_PLAN)

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
    """Approve with commit_plan=True, run_coder=False writes options and sets PLAN COMMITTED."""
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
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
            patch(
                "sase.plan_approval_actions._archive_plan_for_approval",
                return_value=_ApprovedPlanArchive(
                    response_dir / "saved-plan.md",
                    "plan:202608/saved-plan.md",
                ),
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
    assert data["plan_archive_owner"] == "host"
    assert data["saved_plan_path"] == str(response_dir / "saved-plan.md")
    assert data["plan_archive_protocol"] == "host_v2"
    assert data["plan_archive_ref"] == "plan:202608/saved-plan.md"
    assert app._agent_status_overrides[mock_agent.identity] == "PLAN COMMITTED"


def test_approval_choice_response_mapping() -> None:
    """Product approval choices normalize to the legacy runner response protocol."""
    from sase.ace.tui.actions.agents._notification_modals import (
        _build_plan_approval_response,
        _plan_approval_persist_action,
        _plan_approval_status,
    )

    approve = plan_approval_result_for_choice("approve")
    assert _build_plan_approval_response(approve) == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
    }
    assert _plan_approval_status(approve) == "PLAN APPROVED"
    assert _plan_approval_persist_action(approve) == "approve"

    tale = plan_approval_result_for_choice("tale", coder_prompt="#review+")
    assert _build_plan_approval_response(tale) == {
        "action": "approve",
        "commit_plan": True,
        "run_coder": True,
        "coder_prompt": "#review+",
    }
    assert _plan_approval_status(tale) == "TALE APPROVED"
    assert _plan_approval_persist_action(tale) == "tale"

    epic = plan_approval_result_for_choice("epic")
    assert _build_plan_approval_response(epic) == {
        "action": "epic",
        "commit_plan": True,
        "run_coder": True,
    }


def test_plan_modal_defaults_to_authored_tier(tmp_path: Path) -> None:
    app, notification, _response_dir, _mock_agent = make_approval_app_and_notification(
        tmp_path
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    handle_plan_approval(app, notification)

    modal = app.push_screen.call_args.args[0]
    assert modal._default_choice == "tale"


def test_approve_with_prompt_writes_prompt_and_sets_tale_status(
    tmp_path: Path,
) -> None:
    """Approve with commit_plan=True/run_coder=True is shown as a tale approval."""
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
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
            patch(
                "sase.plan_approval_actions._archive_plan_for_approval",
                return_value=_ApprovedPlanArchive(
                    response_dir / "saved-plan.md",
                    "plan:202608/saved-plan.md",
                ),
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
    assert app._agent_status_overrides[mock_agent.identity] == "TALE APPROVED"


def test_approve_archives_plan_before_writing_response(tmp_path: Path) -> None:
    """The agent-unblocking response is published only after archive metadata exists."""
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
        tmp_path
    )
    app._agents_with_children = [mock_agent]
    app.run_worker.side_effect = lambda work, thread=True: work()
    app.call_from_thread.side_effect = lambda callback: callback()

    plan_response_path = response_dir / "plan_response.json"

    saved_plan_path = str(response_dir / "saved-plan.md")

    def archive_side_effect(
        notification: object,
        action: str = "approve",
        *,
        required: bool = False,
    ) -> str:
        assert not plan_response_path.exists()
        assert action == "tale"
        assert required is True
        assert mock_agent.identity not in app._agent_status_overrides
        return _ApprovedPlanArchive(saved_plan_path, "plan:202608/saved-plan.md")

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
            "sase.plan_approval_actions._archive_plan_for_approval",
            side_effect=archive_side_effect,
        ) as archive_plan,
        patch(
            "sase.ace.tui.actions.agents._notification_modals._archive_plan_for_approval"
        ) as background_archive,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(PlanApprovalResult(action="approve"))

    archive_plan.assert_called_once()
    background_archive.assert_not_called()
    data = json.loads(plan_response_path.read_text())
    assert data["saved_plan_path"] == saved_plan_path
    assert data["plan_archive_owner"] == "host"
    assert data["plan_archive_protocol"] == "host_v2"
    assert data["plan_archive_ref"] == "plan:202608/saved-plan.md"


def test_approve_uses_cached_refresh_instead_of_sync_load(tmp_path: Path) -> None:
    """Fast-path status refresh should avoid a synchronous full agent load."""
    app, notification, _response_dir, mock_agent = make_approval_app_and_notification(
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
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=_ApprovedPlanArchive(
                _response_dir / "saved-plan.md",
                "plan:202608/saved-plan.md",
            ),
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
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
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
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=_ApprovedPlanArchive(
                saved_plan_path,
                "plan:202608/plan.md",
            ),
        ),
        patch("sase.ace.tui.actions.clipboard.schedule_copy_delivery") as schedule_copy,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(
            PlanApprovalResult(action="approve", commit_plan=True, run_coder=False)
        )

    assert app._agent_status_overrides[mock_agent.identity] == "PLAN COMMITTED"
    schedule_copy.assert_called_once_with(
        app,
        "~/workspace/.sase/plans/plan.md",
        copied_label=("committed plan path (~/workspace/.sase/plans/plan.md)"),
        task_name="sase-copy-committed-plan-path",
    )
    app._refresh_notification_count.assert_called_once()
    app._schedule_agents_async_refresh.assert_not_called()
    data = json.loads((response_dir / "plan_response.json").read_text())
    assert data["saved_plan_path"] == saved_plan_path
    assert data["plan_archive_protocol"] == "host_v2"
    assert data["plan_archive_ref"] == "plan:202608/plan.md"

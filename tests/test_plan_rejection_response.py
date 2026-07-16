"""Tests for TUI plan approval response handling."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalResult,
    _plan_approval_result_for_choice,
)
from sase.notifications import Notification
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy


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
    plan_file.write_text(VALID_TALE_PLAN)

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


def test_approval_choice_response_mapping() -> None:
    """Product approval choices normalize to the legacy runner response protocol."""
    from sase.ace.tui.actions.agents._notification_modals import (
        _build_plan_approval_response,
        _plan_approval_persist_action,
        _plan_approval_status,
    )

    approve = _plan_approval_result_for_choice("approve")
    assert _build_plan_approval_response(approve) == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
    }
    assert _plan_approval_status(approve) == "PLAN APPROVED"
    assert _plan_approval_persist_action(approve) == "approve"

    tale = _plan_approval_result_for_choice("tale", coder_prompt="#review+")
    assert _build_plan_approval_response(tale) == {
        "action": "approve",
        "commit_plan": True,
        "run_coder": True,
        "coder_prompt": "#review+",
    }
    assert _plan_approval_status(tale) == "TALE APPROVED"
    assert _plan_approval_persist_action(tale) == "tale"

    epic = _plan_approval_result_for_choice("epic")
    assert _build_plan_approval_response(epic) == {
        "action": "epic",
        "commit_plan": True,
        "run_coder": True,
    }


def test_plan_modal_defaults_to_authored_tier(tmp_path: Path) -> None:
    app, notification, _response_dir, _mock_agent = _make_approval_app_and_notification(
        tmp_path
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    handle_plan_approval(app, notification)

    modal = app.push_screen.call_args.args[0]
    assert modal._default_choice == "tale"


def test_tui_failed_epic_gate_keeps_response_unconsumed_until_fixed(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    plan = Path(notification.files[0])

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with patch(
        "sase.ace.tui.actions.agents._notification_navigation.find_agent_for_notification",
        return_value=mock_agent,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]

        on_dismiss(_plan_approval_result_for_choice("epic"))

        assert not (response_dir / "plan_response.json").exists()
        assert (response_dir / "plan_request.json").is_file()
        assert "approval blocked" in app.notify.call_args.kwargs["title"].lower()

        plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
        on_dismiss(_plan_approval_result_for_choice("epic"))

    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["action"] == "epic"


def test_tui_epic_task_is_submitted_before_host_owner_response(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    plan_response_path = response_dir / "plan_response.json"
    order: list[str] = []

    def submit(*_args: object, **_kwargs: object) -> bool:
        assert not plan_response_path.exists()
        order.append("task")
        return True

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation."
            "find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "submit_epic_launch_task",
            side_effect=submit,
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(_plan_approval_result_for_choice("epic"))

    order.append("response")
    response = json.loads(plan_response_path.read_text(encoding="utf-8"))
    assert order == ["task", "response"]
    assert response["epic_launch_owner"] == "host"


def test_tui_epic_submission_failure_preserves_agent_fallback(tmp_path: Path) -> None:
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation."
            "find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "submit_epic_launch_task",
            return_value=False,
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(_plan_approval_result_for_choice("epic"))

    response = json.loads(
        (response_dir / "plan_response.json").read_text(encoding="utf-8")
    )
    assert "epic_launch_owner" not in response


def test_approve_with_prompt_writes_prompt_and_sets_tale_status(
    tmp_path: Path,
) -> None:
    """Approve with commit_plan=True/run_coder=True is shown as a tale approval."""
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
    assert app._agent_status_overrides[mock_agent.identity] == "TALE APPROVED"


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
        assert app._agent_status_overrides[mock_agent.identity] == "TALE APPROVED"

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


def test_archive_plan_for_approval_uses_version_controlled_sdd_dir(
    tmp_path: Path,
) -> None:
    """Version-controlled approval archiving writes under sdd/plans/YYYYMM."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="test-notif",
        timestamp="2026-05-01T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={
            "project_dir": str(tmp_path / "sase_10"),
            "agent_project_file": str(
                tmp_path / "projects" / "canonical" / "canonical.sase"
            ),
        },
        files=[str(plan_file)],
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        _archive_plan_for_approval,
    )

    with (
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ) as get_workspace_directory,
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "epic")

    assert saved == str(workspace / "sdd" / "plans" / "202605" / "plan.md")
    get_workspace_directory.assert_called_once_with("canonical", 1)
    assert Path(saved).read_text(encoding="utf-8").startswith("---\ncreate_time:")
    assert "tier: epic" in Path(saved).read_text(encoding="utf-8")
    assert not (workspace / ".sase" / "sdd" / "plans").exists()
    ensure_sdd.assert_called_once_with(
        str(workspace),
        commit=True,
        push=False,
    )


def test_archive_plan_for_approval_uses_local_sdd_dir(tmp_path: Path) -> None:
    """Local SDD approval archiving uses .sase/sdd/plans/YYYYMM."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="test-notif",
        timestamp="2026-05-01T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"project_dir": str(workspace)},
        files=[str(plan_file)],
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        _archive_plan_for_approval,
    )

    with (
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patched_sdd_policy("local"),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "approve")

    assert saved == str(workspace / ".sase" / "sdd" / "plans" / "202605" / "plan.md")
    assert Path(saved).exists()
    assert "tier: tale" in Path(saved).read_text(encoding="utf-8")
    ensure_sdd.assert_not_called()


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
    app._schedule_agents_async_refresh.assert_not_called()
    data = json.loads((response_dir / "plan_response.json").read_text())
    assert data["saved_plan_path"] == saved_plan_path

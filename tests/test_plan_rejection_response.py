"""Tests for TUI plan approval response handling."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalResult,
    _plan_approval_result_for_choice,
)
from sase.ace.tui.task_queue import TaskInfo
from sase.notifications import Notification
from sase.plan_approval_actions import PlanApprovalActionError
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


def _run_tracked_tasks_immediately(app: MagicMock) -> list[dict[str, Any]]:
    submitted: list[dict[str, Any]] = []

    def submit(
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        task_info = TaskInfo(
            task_id=f"task-{len(submitted)}",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        submitted.append(
            {
                "task_type": task_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "display_name": display_name,
                "dedup_key": dedup_key,
                "task_callable": task_callable,
            }
        )
        result = task_callable()
        task_info.status = "success" if result.success else "error"
        task_info.message = result.message
        task_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedTaskCompletion(
                    task_info=task_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return task_info

    app._submit_tracked_task.side_effect = submit
    return submitted


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


def test_tui_epic_approval_uses_shared_detached_launch(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    plan_response_path = response_dir / "plan_response.json"
    order: list[str] = []
    tracked_tasks = _run_tracked_tasks_immediately(app)

    def submit(*_args: object, **_kwargs: object) -> object:
        response = json.loads(plan_response_path.read_text(encoding="utf-8"))
        assert response["epic_launch_owner"] == "host"
        order.append("detached")
        return object()

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
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=submit,
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(_plan_approval_result_for_choice("epic"))

    response = json.loads(plan_response_path.read_text(encoding="utf-8"))
    assert order == ["detached"]
    assert [task["task_type"] for task in tracked_tasks] == ["launch"]
    assert tracked_tasks[0]["dedup_key"] == "legacy-epic-launch:test-notif"
    assert response["epic_launch_owner"] == "host"


def test_tui_epic_launch_preflight_runs_only_inside_tracked_task(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    submitted: list[dict[str, Any]] = []

    def capture_task(
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        **kwargs: Any,
    ) -> object:
        submitted.append(
            {
                "task_type": task_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "task_callable": task_callable,
                "kwargs": kwargs,
            }
        )
        return object()

    app._submit_tracked_task.side_effect = capture_task

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation."
            "find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch("sase.plan_approval_actions.prepare_epic_launch") as prepare_launch,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(_plan_approval_result_for_choice("epic"))

        prepare_launch.assert_not_called()

    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"
    assert submitted[0]["task_type"] == "launch"
    assert submitted[0]["kwargs"]["dedup_key"] == "legacy-epic-launch:test-notif"


def test_tui_epic_submission_failure_is_loud_and_keeps_host_owner(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = _make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    _run_tracked_tasks_immediately(app)

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
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=PlanApprovalActionError(
                "epic_launch_failed",
                str(notification.files[0]),
                "could not submit; resume with `sase bead work plan.md --yes-to-all`",
            ),
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(_plan_approval_result_for_choice("epic"))

    response = json.loads(
        (response_dir / "plan_response.json").read_text(encoding="utf-8")
    )
    assert response["epic_launch_owner"] == "host"
    app.notify.assert_any_call(
        "could not submit; resume with `sase bead work plan.md --yes-to-all`",
        title="Epic launch failed",
        severity="error",
        timeout=15,
    )


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
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "epic")

    assert saved == str(workspace / "sdd" / "plans" / "202605" / "plan.md")
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

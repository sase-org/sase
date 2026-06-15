"""Test that TUI rejection-without-feedback writes plan_response.json."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalResult,
    _plan_approval_result_for_choice,
)
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

    legend = _plan_approval_result_for_choice("legend")
    assert _build_plan_approval_response(legend) == {
        "action": "legend",
        "commit_plan": True,
        "run_coder": True,
    }


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


def test_archive_plan_for_approval_uses_version_controlled_sdd_dir(
    tmp_path: Path,
) -> None:
    """Version-controlled approval archiving writes under sdd/<kind>/YYYYMM."""
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
        patch("sase.sdd.beads.get_sdd_config", return_value=True),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "legend")

    assert saved == str(workspace / "sdd" / "legends" / "202605" / "plan.md")
    assert Path(saved).read_text(encoding="utf-8").startswith("---\ncreate_time:")
    assert not (workspace / ".sase" / "sdd" / "legends").exists()
    ensure_sdd.assert_called_once_with(
        str(workspace),
        commit=True,
        push=False,
    )


def test_archive_plan_for_approval_uses_local_sdd_dir(tmp_path: Path) -> None:
    """Local SDD approval archiving keeps using .sase/sdd/<kind>/YYYYMM."""
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
        patch("sase.sdd.beads.get_sdd_config", return_value=False),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "approve")

    assert saved == str(workspace / ".sase" / "sdd" / "tales" / "202605" / "plan.md")
    assert Path(saved).exists()
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


def test_user_question_response_dismisses_notification_and_marks_answered(
    tmp_path: Path,
) -> None:
    """Answering a question writes the response, dismisses the source
    notification, and flips the agent to the transient ANSWERED state."""
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
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260425120000",
    )
    app = MagicMock()
    app._agents = [agent]
    app._agents_with_children = [agent]
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
    # The pre-question status is no longer restored; the row shows the
    # transient ANSWERED state until a fresh load reconciles it away.
    assert app._agent_status_overrides[agent.identity] == "ANSWERED"
    assert agent.identity not in app._agent_pre_question_status
    app._refilter_agents.assert_called_once()
    app._schedule_agents_async_refresh.assert_not_called()


def test_user_question_response_marks_root_and_child_answered(
    tmp_path: Path,
) -> None:
    """Answering a question flips BOTH the root row and the asking child row.

    A single UserQuestion notification carries agent_timestamp (the child that
    asked) and agent_root_timestamp (the visible root/aggregate row). Both rows
    can be loaded and each keeps its own QUESTION override keyed by identity, so
    the answer must clear both — otherwise the child sticks on stale QUESTION.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps({"questions": [{"question": "Pick one"}]})
    )

    notification = Notification(
        id="question-notif",
        timestamp="2026-05-12T09:43:33-04:00",
        sender="test",
        action="UserQuestion",
        action_data={
            "response_dir": str(response_dir),
            "agent_cl_name": "my_cl",
            "agent_timestamp": "20260512094333",
            "agent_root_timestamp": "20260512090000",
        },
    )
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260512094333",
        parent_timestamp="20260512090000",
        parent_workflow="my_cl.plan",
    )
    app = MagicMock()
    app._agents = [root, child]
    app._agents_with_children = [root, child]
    app._agent_status_overrides = {
        root.identity: "QUESTION",
        child.identity: "QUESTION",
    }
    app._agent_pre_question_status = {
        root.identity: "RUNNING",
        child.identity: "RUNNING",
    }

    from sase.ace.tui.actions.agents._notification_modals import handle_user_question

    assert handle_user_question(app, notification) is True
    on_dismiss = app.push_screen.call_args[0][1]

    with patch("sase.notifications.mark_dismissed"):
        on_dismiss(
            UserQuestionResult(
                answers=[
                    _QuestionAnswer(
                        question="Pick one",
                        selected=["A"],
                        custom_feedback=None,
                    )
                ],
                global_note="",
            )
        )

    assert (response_dir / "question_response.json").exists()
    assert app._agent_status_overrides[root.identity] == "ANSWERED"
    assert app._agent_status_overrides[child.identity] == "ANSWERED"
    assert root.identity not in app._agent_pre_question_status
    assert child.identity not in app._agent_pre_question_status
    app._refilter_agents.assert_called()


def test_open_user_question_modal_from_marker_marks_root_row(tmp_path: Path) -> None:
    """The marker fallback also flips the loaded root row when supplied a child.

    With no notification carrying both timestamps, the related root/aggregate
    row is resolved from the child's parent_timestamp so both stay in sync.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps({"questions": [{"question": "Resume from marker?"}]})
    )

    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260512090000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260512094333",
        parent_timestamp="20260512090000",
        parent_workflow="my_cl.plan",
    )
    app = MagicMock()
    app._agents = [root, child]
    app._agents_with_children = [root, child]
    app._agent_status_overrides = {
        root.identity: "QUESTION",
        child.identity: "QUESTION",
    }
    app._agent_pre_question_status = {
        root.identity: "RUNNING",
        child.identity: "RUNNING",
    }

    from sase.ace.tui.actions.agents._notification_modals import (
        open_user_question_modal_from_marker,
    )

    assert open_user_question_modal_from_marker(app, str(response_dir), child) is True
    on_dismiss = app.push_screen.call_args[0][1]

    on_dismiss(
        UserQuestionResult(
            answers=[
                _QuestionAnswer(
                    question="Resume from marker?",
                    selected=["yes"],
                    custom_feedback=None,
                )
            ],
            global_note="",
        )
    )

    assert (response_dir / "question_response.json").exists()
    assert app._agent_status_overrides[child.identity] == "ANSWERED"
    assert app._agent_status_overrides[root.identity] == "ANSWERED"
    assert child.identity not in app._agent_pre_question_status
    assert root.identity not in app._agent_pre_question_status


def test_open_user_question_modal_from_marker_dismissed_notification(
    tmp_path: Path,
) -> None:
    """The fallback opens the modal directly from a pending_question marker.

    When the UserQuestion notification has already been dismissed (the bug
    fixed by the pending_question.json marker), the "jump to current agent's
    question" keybind must still be able to open the modal by reading the
    request_path out of the marker.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps({"questions": [{"question": "Resume from marker?"}]})
    )

    app = MagicMock()

    from sase.ace.tui.actions.agents._notification_modals import (
        open_user_question_modal_from_marker,
    )

    assert open_user_question_modal_from_marker(app, str(response_dir)) is True
    on_dismiss = app.push_screen.call_args[0][1]

    on_dismiss(
        UserQuestionResult(
            answers=[
                _QuestionAnswer(
                    question="Resume from marker?",
                    selected=["yes"],
                    custom_feedback=None,
                )
            ],
            global_note="",
        )
    )

    response_data = json.loads((response_dir / "question_response.json").read_text())
    assert response_data == {
        "answers": [
            {
                "question": "Resume from marker?",
                "selected": ["yes"],
                "custom_feedback": None,
            }
        ],
        "global_note": "",
    }


def test_open_user_question_modal_from_marker_marks_answered(tmp_path: Path) -> None:
    """The marker fallback flips the supplied agent to ANSWERED on response.

    Mirrors the notification-driven path: answering from a dismissed-notification
    marker records the transient ANSWERED override for the matched agent.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps({"questions": [{"question": "Resume from marker?"}]})
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="QUESTION",
        start_time=None,
        raw_suffix="20260425120000",
    )
    app = MagicMock()
    app._agents = [agent]
    app._agent_status_overrides = {agent.identity: "QUESTION"}
    app._agent_pre_question_status = {agent.identity: "RUNNING"}

    from sase.ace.tui.actions.agents._notification_modals import (
        open_user_question_modal_from_marker,
    )

    assert open_user_question_modal_from_marker(app, str(response_dir), agent) is True
    on_dismiss = app.push_screen.call_args[0][1]

    on_dismiss(
        UserQuestionResult(
            answers=[
                _QuestionAnswer(
                    question="Resume from marker?",
                    selected=["yes"],
                    custom_feedback=None,
                )
            ],
            global_note="",
        )
    )

    assert (response_dir / "question_response.json").exists()
    assert app._agent_status_overrides[agent.identity] == "ANSWERED"
    assert agent.identity not in app._agent_pre_question_status


def test_open_user_question_modal_from_marker_missing_request(tmp_path: Path) -> None:
    """A missing question_request.json surfaces a warning and returns False."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()

    app = MagicMock()

    from sase.ace.tui.actions.agents._notification_modals import (
        open_user_question_modal_from_marker,
    )

    assert open_user_question_modal_from_marker(app, str(response_dir)) is False
    app.push_screen.assert_not_called()
    app.notify.assert_called_once()

"""Tests for TUI user-question response handling."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.user_question_modal import (
    UserQuestionResult,
    _QuestionAnswer,
)
from sase.notification_gates.service import create_gate
from sase.notifications import Notification
from sase.notifications.store import load_notifications
from sase.user_question_actions import user_question_gate_spec


def test_neutral_question_response_uses_one_durable_proc() -> None:
    gate = create_gate(
        user_question_gate_spec(
            [{"question": "Tracked?", "options": [{"label": "Yes"}]}],
            session_id="tracked-question",
        )
    )
    notification = load_notifications()[0]
    app = MagicMock()
    app._agents = []
    app._agent_status_overrides = {}
    submitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def submit(*args: object, **kwargs: object) -> object:
        submitted.append((args, kwargs))
        return object()

    app._submit_durable_proc = submit
    app._submit_session_worker = MagicMock(
        side_effect=AssertionError("neutral answers must use a durable proc")
    )
    response_written = MagicMock()
    from sase.ace.tui.actions.agents import _notification_question_modal

    with (
        patch.object(
            _notification_question_modal,
            "_on_user_question_response_written",
            response_written,
        ),
        patch(
            "sase.user_question_actions.execute_user_question_response"
        ) as execute_in_process,
        patch(
            "sase.ace.tui.actions.agents._notification_utils.schedule_gate_decision_receipt_refresh"
        ) as refresh_receipt,
        patch(
            "sase.user_question_actions.run_user_question_response_side_effects"
        ) as run_side_effects,
    ):
        from sase.ace.tui.actions.agents._notification_modals import (
            handle_user_question,
        )

        assert handle_user_question(app, notification) is True
        on_dismiss = app.push_screen.call_args[0][1]
        on_dismiss(
            UserQuestionResult(
                answers=[
                    _QuestionAnswer(
                        question="Tracked?",
                        selected=["Yes"],
                        custom_feedback=None,
                    )
                ],
                global_note="",
            )
        )

        assert len(submitted) == 1
        args, kwargs = submitted[0]
        request_id = str(
            notification.action_data.get("request_id") or gate.bundle_path.name
        )
        assert args[0] == [
            "sase",
            "gate",
            "answer",
            "--id",
            request_id,
            "--kind",
            "question",
            "--no-detach",
            "--json",
        ]
        assert kwargs["operation"] == "gate.answer"
        assert kwargs["request"] == {
            "option_ids": ["submit"],
            "input_data": {
                "answers": [
                    {
                        "question": "Tracked?",
                        "selected": ["Yes"],
                        "custom_feedback": None,
                    }
                ],
                "global_note": "",
            },
            "feedback": None,
            "source": "tui",
        }
        assert kwargs["concurrency_keys"] == (f"notification-gate:{notification.id}",)
        assert kwargs["display_name"] == f"answer question {request_id}"
        assert gate.response_path.exists() is False
        execute_in_process.assert_not_called()

        kwargs["on_complete"](
            SimpleNamespace(
                payload={"status": "answered"},
                success=True,
                message="Question answered",
            )
        )

    response_written.assert_called_once()
    refresh_receipt.assert_called_once_with(
        app,
        notification=notification,
        bundle_path=gate.bundle_path,
    )
    run_side_effects.assert_called_once()
    (context,) = run_side_effects.call_args.args
    assert context.notification_id == notification.id
    assert context.host_action_data["response_dir"] == str(gate.bundle_path)
    assert run_side_effects.call_args.kwargs == {"source": "tui"}
    app.notify.assert_called_once_with("Question answered")
    app._refresh_notification_count.assert_called_once()


def test_invalid_neutral_question_answer_fails_before_submission() -> None:
    create_gate(
        user_question_gate_spec(
            [{"question": "Pick?", "options": [{"label": "Yes"}]}],
            session_id="invalid-question-answer",
        )
    )
    notification = load_notifications()[0]
    app = MagicMock()
    app._agents = []
    app._agent_status_overrides = {}
    app._submit_durable_proc = MagicMock()

    from sase.ace.tui.actions.agents._notification_modals import handle_user_question

    assert handle_user_question(app, notification) is True
    app.push_screen.call_args[0][1](
        UserQuestionResult(
            answers=[
                _QuestionAnswer(
                    question="Pick?",
                    selected=["No"],
                    custom_feedback=None,
                )
            ],
            global_note="",
        )
    )

    app._submit_durable_proc.assert_not_called()
    app.notify.assert_called_once()
    assert app.notify.call_args.kwargs["severity"] == "error"


@pytest.mark.parametrize("code", ["already_answered", "gate_cancelled"])
def test_durable_question_maps_answered_failures_to_warning(code: str) -> None:
    create_gate(
        user_question_gate_spec(
            [{"question": "Already?", "options": [{"label": "Yes"}]}],
            session_id=f"already-{code}",
        )
    )
    notification = load_notifications()[0]
    app = MagicMock()
    app._agents = []
    app._agent_status_overrides = {}
    submitted: dict[str, object] = {}

    def submit(*_args: object, **kwargs: object) -> object:
        submitted.update(kwargs)
        return object()

    app._submit_durable_proc = submit

    from sase.ace.tui.actions.agents._notification_modals import handle_user_question

    assert handle_user_question(app, notification) is True
    app.push_screen.call_args[0][1](
        UserQuestionResult(
            answers=[
                _QuestionAnswer(
                    question="Already?",
                    selected=["Yes"],
                    custom_feedback=None,
                )
            ],
            global_note="",
        )
    )
    submitted["on_complete"](
        SimpleNamespace(success=False, message="answer failed", payload={"code": code})
    )

    app.notify.assert_called_once_with(
        "Question was already answered",
        severity="warning",
    )
    app._refresh_notification_count.assert_called_once()


def test_user_question_response_dismisses_notification_and_marks_answered(
    tmp_path: Path,
) -> None:
    """Answering a question writes the response, dismisses the source
    notification, and flips the agent to the transient ANSWERED state."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps(
            {"questions": [{"question": "Pick one", "options": [{"label": "A"}]}]}
        )
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
    app._submit_session_worker = None
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._agent_status_overrides = {agent.identity: "QUESTION"}

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
    # The row shows the transient ANSWERED state until a fresh load
    # reconciles it away.
    assert app._agent_status_overrides[agent.identity] == "ANSWERED"
    app._refilter_agents.assert_called_once()
    app._schedule_agents_async_refresh.assert_not_called()


def test_user_question_response_marks_root_and_child_answered(
    tmp_path: Path,
) -> None:
    """Answering a question flips BOTH the root row and the asking child row.

    A single UserQuestion notification carries agent_timestamp (the child that
    asked) and agent_root_timestamp (the visible root/aggregate row). Both rows
    can be loaded and each keeps its own QUESTION override keyed by identity, so
    the answer must clear both; otherwise the child sticks on stale QUESTION.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps(
            {"questions": [{"question": "Pick one", "options": [{"label": "A"}]}]}
        )
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
    app._submit_session_worker = None
    app._agents = [root, child]
    app._agents_with_children = [root, child]
    app._agent_status_overrides = {
        root.identity: "QUESTION",
        child.identity: "QUESTION",
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
    app._refilter_agents.assert_called()


def test_open_user_question_modal_from_marker_marks_root_row(tmp_path: Path) -> None:
    """The marker fallback also flips the loaded root row when supplied a child.

    With no notification carrying both timestamps, the related root/aggregate
    row is resolved from the child's parent_timestamp so both stay in sync.
    """
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps(
            {
                "questions": [
                    {"question": "Resume from marker?", "options": [{"label": "yes"}]}
                ]
            }
        )
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
    app._submit_session_worker = None
    app._agents = [root, child]
    app._agents_with_children = [root, child]
    app._agent_status_overrides = {
        root.identity: "QUESTION",
        child.identity: "QUESTION",
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
        json.dumps(
            {
                "questions": [
                    {"question": "Resume from marker?", "options": [{"label": "yes"}]}
                ]
            }
        )
    )

    app = MagicMock()
    app._submit_session_worker = None

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
        json.dumps(
            {
                "questions": [
                    {"question": "Resume from marker?", "options": [{"label": "yes"}]}
                ]
            }
        )
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
    app._submit_session_worker = None
    app._agents = [agent]
    app._agent_status_overrides = {agent.identity: "QUESTION"}

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

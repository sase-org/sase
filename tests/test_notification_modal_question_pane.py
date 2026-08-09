"""Rendering tests for the notification modal's question preview."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_question import (
    NotificationQuestionMixin,
)
from sase.notifications import Notification


class _QuestionPane(NotificationQuestionMixin):
    def __init__(self) -> None:
        self.app = SimpleNamespace(_agents=[])


def _notification(response_dir: Path) -> Notification:
    return Notification(
        id="question-1",
        timestamp="2026-07-14T08:00:00-04:00",
        sender="question",
        notes=["How should I proceed?"],
        action="UserQuestion",
        action_data={
            "response_dir": str(response_dir),
            "session_id": "3f2a12345678",
            "agent_cl_name": "memory-protection",
            "agent_timestamp": "20260714080000",
        },
    )


def _write_request(response_dir: Path) -> None:
    response_dir.mkdir(parents=True, exist_ok=True)
    (response_dir / "question_request.json").write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "header": "Protected memory regenerated",
                        "question": (
                            "The commit hook regenerated protected files. "
                            "How should I proceed?"
                        ),
                        "options": [
                            {
                                "label": "Amend and keep",
                                "description": "Fold the files into this commit",
                            },
                            {
                                "label": "Abort",
                                "description": "Let me inspect manually",
                            },
                        ],
                    }
                ],
                "session_id": "3f2a12345678",
            }
        ),
        encoding="utf-8",
    )


def _render_plain(renderable: object) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_awaiting_question_pane_contains_identity_prompt_and_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_dir = tmp_path / "question"
    _write_request(response_dir)
    agent = SimpleNamespace(
        agent_name="codex--fix-hook",
        display_name="memory-protection",
        llm_provider="codex",
        model="gpt-5.6-sol",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_question.find_agent_for_notification",
        lambda _app, _notification: agent,
    )

    pane = _QuestionPane()._render_question_pane(_notification(response_dir))

    assert pane is not None
    title, content = pane
    plain = _render_plain(content)
    assert title == "Agent Question"
    assert "Question from codex--fix-hook" in plain
    assert "CODEX(gpt-5.6-sol)" in plain
    assert "Patch memory-protection · session 3f2a1234…" in plain
    assert "Awaiting your answer" in plain
    assert "press Enter to answer" in plain
    assert "Protected memory regenerated" in plain
    assert "The commit hook regenerated protected files" in plain
    assert "Amend and keep" in plain
    assert "Abort" in plain
    assert "single-select" in plain


def test_answered_question_pane_shows_selected_choice_and_note(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "question"
    _write_request(response_dir)
    (response_dir / "question_response.json").write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "question": (
                            "The commit hook regenerated protected files. "
                            "How should I proceed?"
                        ),
                        "selected": ["Amend and keep"],
                        "custom_feedback": None,
                    }
                ],
                "global_note": "Keep the generated index too",
            }
        ),
        encoding="utf-8",
    )

    pane = _QuestionPane()._render_question_pane(_notification(response_dir))

    assert pane is not None
    plain = _render_plain(pane[1])
    assert "✓ Answered" in plain
    assert "You chose: Amend and keep" in plain
    assert "Note: Keep the generated index too" in plain
    assert "● Amend and keep" in plain


def test_expired_question_pane_uses_notification_fallback(tmp_path: Path) -> None:
    response_dir = tmp_path / "question"
    response_dir.mkdir()

    pane = _QuestionPane()._render_question_pane(_notification(response_dir))

    assert pane is not None
    plain = _render_plain(pane[1])
    assert "Expired or already handled" in plain
    assert "request is no longer active" in plain
    assert "How should I proceed?" in plain


def test_non_question_has_no_question_pane(tmp_path: Path) -> None:
    notification = _notification(tmp_path)
    notification.action = "PlanApproval"

    assert _QuestionPane()._render_question_pane(notification) is None


def test_display_file_dispatches_question_before_empty_attachment_state(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "question"
    _write_request(response_dir)
    notification = _notification(response_dir)
    modal = NotificationModal([notification])
    title = MagicMock()
    content = MagicMock()

    def query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        raise LookupError(selector)

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    modal._set_image_preview_mode = MagicMock()  # type: ignore[method-assign]
    modal._reset_file_scroll = MagicMock()  # type: ignore[method-assign]

    modal._display_file(notification)

    title.update.assert_called_once_with("❓ question · Agent Question")
    plain = _render_plain(content.update.call_args.args[0])
    assert "Awaiting your answer" in plain
    assert "No files attached" not in plain
    modal._set_image_preview_mode.assert_called_once_with(False)
    modal._reset_file_scroll.assert_called_once_with()


def test_question_highlight_uses_answer_focused_footer(tmp_path: Path) -> None:
    notification = _notification(tmp_path)
    modal = NotificationModal([notification])
    footer = MagicMock()
    modal._get_highlighted_notification = (  # type: ignore[method-assign]
        lambda: notification
    )
    modal.query_one = MagicMock(return_value=footer)  # type: ignore[method-assign]

    modal._update_hint_footer()

    hint = footer.update.call_args.args[0]
    assert hint.startswith("Enter: answer")
    assert "C-d/C-u: scroll" in hint
    assert "copy path" not in hint

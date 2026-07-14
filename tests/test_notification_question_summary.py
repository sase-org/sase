"""Tests for presentation-independent question notification summaries."""

from __future__ import annotations

import json
from pathlib import Path

from sase.notifications import (
    Notification,
    build_question_summary,
    question_answer_state,
)


def _notification(
    response_dir: Path | None,
    *,
    action: str = "UserQuestion",
    notes: list[str] | None = None,
) -> Notification:
    action_data = {
        "agent_cl_name": "memory-protection",
        "session_id": "session-123456",
    }
    if response_dir is not None:
        action_data["response_dir"] = str(response_dir)
    return Notification(
        id="question-1",
        timestamp="2026-07-14T08:00:00-04:00",
        sender="question",
        notes=notes or ["How should I proceed?"],
        action=action,
        action_data=action_data,
    )


def _write_request(response_dir: Path, questions: list[dict[str, object]]) -> None:
    response_dir.mkdir(parents=True, exist_ok=True)
    (response_dir / "question_request.json").write_text(
        json.dumps(
            {
                "questions": questions,
                "session_id": "request-session",
                "timestamp": 1,
            }
        ),
        encoding="utf-8",
    )


def test_non_question_notification_has_no_summary(tmp_path: Path) -> None:
    assert (
        build_question_summary(_notification(tmp_path, action="PlanApproval")) is None
    )


def test_builds_awaiting_single_question_with_options(tmp_path: Path) -> None:
    response_dir = tmp_path / "question"
    _write_request(
        response_dir,
        [
            {
                "header": "Protected memory regenerated",
                "question": "How should I proceed?",
                "options": [
                    {"label": "Amend", "description": "Keep regenerated files"},
                    {"label": "Abort", "description": "Inspect manually"},
                ],
            }
        ],
    )

    summary = build_question_summary(_notification(response_dir))

    assert summary is not None
    assert summary.answer_state == "awaiting"
    assert summary.detail_available is True
    assert summary.asker_cl_name == "memory-protection"
    assert summary.session_id == "session-123456"
    assert len(summary.questions) == 1
    question = summary.questions[0]
    assert question.header == "Protected memory regenerated"
    assert question.prompt == "How should I proceed?"
    assert question.multi_select is False
    assert [(option.label, option.description) for option in question.options] == [
        ("Amend", "Keep regenerated files"),
        ("Abort", "Inspect manually"),
    ]


def test_builds_multiple_questions_and_multi_select(tmp_path: Path) -> None:
    response_dir = tmp_path / "question"
    _write_request(
        response_dir,
        [
            {"question": "Which path?", "options": [{"label": "Safe"}]},
            {
                "header": "Checks",
                "question": "Which checks should run?",
                "options": [{"label": "Unit"}, {"label": "Visual"}],
                "multiSelect": True,
            },
        ],
    )

    summary = build_question_summary(_notification(response_dir))

    assert summary is not None
    assert [question.prompt for question in summary.questions] == [
        "Which path?",
        "Which checks should run?",
    ]
    assert summary.questions[1].multi_select is True


def test_missing_response_dir_is_unavailable_with_fallback() -> None:
    summary = build_question_summary(
        _notification(None, notes=["Original notification question"])
    )

    assert summary is not None
    assert summary.answer_state == "unavailable"
    assert summary.detail_available is False
    assert summary.fallback_note == "Original notification question"


def test_missing_request_in_existing_directory_is_expired(tmp_path: Path) -> None:
    response_dir = tmp_path / "question"
    response_dir.mkdir()

    notification = _notification(response_dir)
    summary = build_question_summary(notification)

    assert question_answer_state(notification) == "expired"
    assert summary is not None
    assert summary.answer_state == "expired"
    assert summary.questions == ()
    assert summary.detail_available is False


def test_corrupt_request_keeps_awaiting_state_and_fallback(tmp_path: Path) -> None:
    response_dir = tmp_path / "question"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text("{broken", encoding="utf-8")

    summary = build_question_summary(
        _notification(response_dir, notes=["Choose a recovery path"])
    )

    assert summary is not None
    assert summary.answer_state == "awaiting"
    assert summary.detail_available is False
    assert summary.questions == ()
    assert summary.fallback_note == "Choose a recovery path"


def test_answered_summary_marks_choices_and_includes_notes(tmp_path: Path) -> None:
    response_dir = tmp_path / "question"
    _write_request(
        response_dir,
        [
            {
                "question": "Which checks should run?",
                "options": [
                    {"label": "Unit"},
                    {"label": "Visual"},
                    {"label": "None"},
                ],
                "multiSelect": True,
            },
            {
                "question": "Anything else?",
                "options": [],
            },
        ],
    )
    (response_dir / "question_response.json").write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "question": "Which checks should run?",
                        "selected": ["Unit", "Visual"],
                        "custom_feedback": None,
                    },
                    {
                        "question": "Anything else?",
                        "selected": [],
                        "custom_feedback": "Run the smoke test too",
                    },
                ],
                "global_note": "Proceed once green",
            }
        ),
        encoding="utf-8",
    )

    summary = build_question_summary(_notification(response_dir))

    assert summary is not None
    assert summary.answer_state == "answered"
    assert summary.detail_available is True
    assert [option.selected for option in summary.questions[0].options] == [
        True,
        True,
        False,
    ]
    assert summary.questions[1].custom_answer == "Run the smoke test too"
    assert summary.global_note == "Proceed once green"


def test_answered_without_request_recovers_details_from_response(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "question"
    response_dir.mkdir()
    (response_dir / "question_response.json").write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "question": "Which path?",
                        "selected": ["Safe"],
                        "custom_feedback": None,
                    }
                ],
                "global_note": "Ship it",
            }
        ),
        encoding="utf-8",
    )

    summary = build_question_summary(_notification(response_dir))

    assert summary is not None
    assert summary.answer_state == "answered"
    assert summary.detail_available is False
    assert summary.questions[0].prompt == "Which path?"
    assert summary.questions[0].options[0].selected is True
    assert summary.global_note == "Ship it"

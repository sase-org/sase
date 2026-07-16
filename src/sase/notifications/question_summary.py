"""Read-only summaries for user-question notifications."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.paths import (
    ResolvedGateBundle,
    resolve_notification_bundle,
)
from sase.notifications.models import Notification

AnswerState = Literal["awaiting", "answered", "expired", "unavailable"]


@dataclass(frozen=True)
class QuestionOption:
    """One choice offered by an agent question."""

    label: str
    description: str | None = None
    selected: bool = False


@dataclass(frozen=True)
class QuestionEntry:
    """One question and its available response choices."""

    prompt: str
    header: str | None
    options: tuple[QuestionOption, ...]
    multi_select: bool
    custom_answer: str | None = None


@dataclass(frozen=True)
class QuestionSummary:
    """Presentation-independent question notification details."""

    asker_cl_name: str | None
    session_id: str | None
    answer_state: AnswerState
    questions: tuple[QuestionEntry, ...]
    global_note: str | None = None
    detail_available: bool = True
    fallback_note: str | None = None


@dataclass(frozen=True)
class _QuestionAnswer:
    prompt: str
    selected: tuple[str, ...]
    custom_feedback: str | None


def is_question_notification(notification: Notification) -> bool:
    """Return whether *notification* represents an agent question."""
    return notification.action == "UserQuestion"


def question_answer_state(notification: Notification) -> AnswerState:
    """Derive question state using the pending-action filesystem rules."""
    bundle = _question_bundle(notification)
    if bundle is None:
        return "unavailable"

    try:
        if bundle.response.exists():
            return "answered"
        if bundle.cancellation.exists():
            return "expired"
        if bundle.request.exists():
            return "awaiting"
        if bundle.root.is_dir():
            return "expired"
    except OSError:
        return "unavailable"
    return "unavailable"


def build_question_summary(notification: Notification) -> QuestionSummary | None:
    """Build a defensive question summary, or ``None`` for other actions."""
    if not is_question_notification(notification):
        return None

    fallback_note = _fallback_note(notification)
    bundle = _question_bundle(notification)
    answer_state = question_answer_state(notification)
    base = QuestionSummary(
        asker_cl_name=_clean_text(notification.action_data.get("agent_cl_name")),
        session_id=_clean_text(notification.action_data.get("session_id")),
        answer_state=answer_state,
        questions=(),
        detail_available=False,
        fallback_note=fallback_note,
    )
    if bundle is None:
        return base

    questions: tuple[QuestionEntry, ...] = ()
    request_ok = False
    try:
        request_data = _read_json_object(bundle.request)
        if not bundle.legacy and isinstance(request_data.get("payload"), dict):
            request_data = request_data["payload"]
        questions = _parse_questions(request_data)
        request_ok = True
        request_session_id = _clean_text(request_data.get("session_id"))
        if base.session_id is None and request_session_id is not None:
            base = replace(base, session_id=request_session_id)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    if answer_state != "answered":
        return replace(
            base,
            questions=questions,
            detail_available=request_ok,
        )

    answers: tuple[_QuestionAnswer, ...] = ()
    global_note: str | None = None
    response_ok = False
    try:
        response_data = _read_json_object(bundle.response)
        if not bundle.legacy and isinstance(response_data.get("result"), dict):
            response_data = response_data["result"]
        answers, global_note = _parse_answers(response_data)
        response_ok = True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    if questions and response_ok:
        questions = _apply_answers(questions, answers)
    elif not questions and answers:
        questions = _questions_from_answers(answers)

    return replace(
        base,
        questions=questions,
        global_note=global_note,
        detail_available=request_ok and response_ok,
    )


def _question_bundle(notification: Notification) -> ResolvedGateBundle | None:
    return resolve_notification_bundle(notification)


def _fallback_note(notification: Notification) -> str:
    for note in notification.notes:
        cleaned = _clean_text(note)
        if cleaned is not None:
            return cleaned
    return "Question details are unavailable."


def _read_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path.name}")
    return value


def _parse_questions(data: dict[str, Any]) -> tuple[QuestionEntry, ...]:
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("question request is missing questions")

    questions: list[QuestionEntry] = []
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            raise ValueError("question entry must be an object")
        prompt = _required_text(raw_question.get("question"), "question")
        header = _optional_text(raw_question.get("header"), "header")
        options = _parse_options(raw_question.get("options", []))
        multi_select = raw_question.get("multiSelect", False)
        if not isinstance(multi_select, bool):
            raise ValueError("multiSelect must be a boolean")
        questions.append(
            QuestionEntry(
                prompt=prompt,
                header=header,
                options=options,
                multi_select=multi_select,
            )
        )
    return tuple(questions)


def _parse_options(value: object) -> tuple[QuestionOption, ...]:
    if not isinstance(value, list):
        raise ValueError("options must be a list")
    options: list[QuestionOption] = []
    for raw_option in value:
        if not isinstance(raw_option, dict):
            raise ValueError("question option must be an object")
        options.append(
            QuestionOption(
                label=_required_text(raw_option.get("label"), "option label"),
                description=_optional_text(
                    raw_option.get("description"), "option description"
                ),
            )
        )
    return tuple(options)


def _parse_answers(
    data: dict[str, Any],
) -> tuple[tuple[_QuestionAnswer, ...], str | None]:
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, list):
        raise ValueError("question response is missing answers")

    answers: list[_QuestionAnswer] = []
    for raw_answer in raw_answers:
        if not isinstance(raw_answer, dict):
            raise ValueError("question answer must be an object")
        raw_selected = raw_answer.get("selected", [])
        if not isinstance(raw_selected, list) or not all(
            isinstance(label, str) for label in raw_selected
        ):
            raise ValueError("selected answers must be a list of strings")
        answers.append(
            _QuestionAnswer(
                prompt=_required_text(raw_answer.get("question"), "answer question"),
                selected=tuple(
                    label.strip() for label in raw_selected if label.strip()
                ),
                custom_feedback=_optional_text(
                    raw_answer.get("custom_feedback"), "custom feedback"
                ),
            )
        )
    global_note = _optional_text(data.get("global_note"), "global note")
    return tuple(answers), global_note


def _apply_answers(
    questions: tuple[QuestionEntry, ...],
    answers: tuple[_QuestionAnswer, ...],
) -> tuple[QuestionEntry, ...]:
    unused = list(enumerate(answers))
    answered_questions: list[QuestionEntry] = []
    for question_index, question in enumerate(questions):
        matched: tuple[int, _QuestionAnswer] | None = next(
            (
                candidate
                for candidate in unused
                if candidate[1].prompt == question.prompt
            ),
            None,
        )
        if matched is None:
            matched = next(
                (candidate for candidate in unused if candidate[0] == question_index),
                None,
            )
        if matched is None:
            answered_questions.append(question)
            continue

        unused.remove(matched)
        answer = matched[1]
        selected = set(answer.selected)
        answered_questions.append(
            replace(
                question,
                options=tuple(
                    replace(option, selected=option.label in selected)
                    for option in question.options
                ),
                custom_answer=answer.custom_feedback,
            )
        )
    return tuple(answered_questions)


def _questions_from_answers(
    answers: tuple[_QuestionAnswer, ...],
) -> tuple[QuestionEntry, ...]:
    return tuple(
        QuestionEntry(
            prompt=answer.prompt,
            header=None,
            options=tuple(
                QuestionOption(label=label, selected=True) for label in answer.selected
            ),
            multi_select=len(answer.selected) > 1,
            custom_answer=answer.custom_feedback,
        )
        for answer in answers
    )


def _clean_text(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _required_text(value: object, field_name: str) -> str:
    cleaned = _clean_text(value)
    if cleaned is None:
        raise ValueError(f"{field_name} must be a non-empty string")
    return cleaned


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return _clean_text(value)

"""Tests for the Rust-backed question-copy facade."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core import question_copy_facade
from tests._rust_extension_module_helpers import install_fake_rust_extension


def test_normalize_questions_copy_canonicalizes_and_omits_empty_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    def normalize(value: Any) -> list[dict[str, str]]:
        seen.append(value)
        if value == []:
            return []
        return [{"text": "/Users/bryan/.cargo", "label": "Cargo"}]

    install_fake_rust_extension(monkeypatch, normalize_question_copy=normalize)
    questions = [
        {"question": "Path?", "copy": ["/Users/bryan/.cargo\n"]},
        {"question": "No values?", "copy": []},
        {"question": "No copy field?"},
    ]

    normalized = question_copy_facade.normalize_questions_copy(questions)

    assert seen == [["/Users/bryan/.cargo\n"], []]
    assert normalized == [
        {
            "question": "Path?",
            "copy": [{"text": "/Users/bryan/.cargo", "label": "Cargo"}],
        },
        {"question": "No values?"},
        {"question": "No copy field?"},
    ]
    assert questions[0]["copy"] == ["/Users/bryan/.cargo\n"]


def test_normalize_questions_copy_rewrites_errors_with_question_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def normalize(_value: Any) -> None:
        raise ValueError(
            "invalid_question_copy: copy[3].text: contains control character U+001B"
        )

    install_fake_rust_extension(monkeypatch, normalize_question_copy=normalize)
    with pytest.raises(question_copy_facade.QuestionCopyValidationError) as exc_info:
        question_copy_facade.normalize_questions_copy(
            [{"question": "Safe?"}, {"question": "Path?", "copy": ["x"]}]
        )

    assert exc_info.value.target == "question[1].copy[3].text"
    assert str(exc_info.value) == (
        "question[1].copy[3].text: contains control character U+001B"
    )


def test_display_question_copy_items_returns_frozen_typed_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch,
        display_question_copy=lambda value: {
            "items": [
                {"text": "chrome://settings"},
                {"text": "/Users/bryan/.cargo", "label": "Cargo"},
            ],
            "unavailable": 2 if value is not None else 0,
        },
    )

    display = question_copy_facade.display_question_copy_items(
        {"question": "Where?", "copy": ["old"]}
    )

    assert display == question_copy_facade.QuestionCopyDisplay(
        items=(
            question_copy_facade.QuestionCopyItem("chrome://settings"),
            question_copy_facade.QuestionCopyItem("/Users/bryan/.cargo", "Cargo"),
        ),
        unavailable=2,
    )
    with pytest.raises(AttributeError):
        display.unavailable = 0  # type: ignore[misc]


def test_display_question_copy_items_treats_missing_copy_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    def display(value: Any) -> dict[str, Any]:
        seen.append(value)
        return {"items": [], "unavailable": 0}

    install_fake_rust_extension(monkeypatch, display_question_copy=display)
    assert question_copy_facade.display_question_copy_items({"question": "Q?"}) == (
        question_copy_facade.QuestionCopyDisplay(items=(), unavailable=0)
    )
    assert seen == [None]


def test_detect_question_copy_candidates_returns_typed_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, list[str]]] = []

    def detect(question_text: str, declared: list[str]) -> list[dict[str, str]]:
        seen.append((question_text, declared))
        return [
            {"text": "--verbose", "kind": "code"},
            {"text": "plan:202611/example.md", "kind": "ref"},
        ]

    install_fake_rust_extension(monkeypatch, detect_question_copy_candidates=detect)
    candidates = question_copy_facade.detect_question_copy_candidates(
        "Run `--verbose`; see plan:202611/example.md.", ("declared",)
    )
    assert seen == [("Run `--verbose`; see plan:202611/example.md.", ["declared"])]
    assert candidates == (
        question_copy_facade.QuestionCopyCandidate("--verbose", "code"),
        question_copy_facade.QuestionCopyCandidate("plan:202611/example.md", "ref"),
    )

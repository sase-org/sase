"""Python facade for the Rust question-copy contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class QuestionCopyItem:
    """One validated text value that can be copied from a question."""

    text: str
    label: str | None = None


@dataclass(frozen=True)
class QuestionCopyDisplay:
    """Tolerant display result, including invalid stored entries."""

    items: tuple[QuestionCopyItem, ...]
    unavailable: int


class QuestionCopyValidationError(ValueError):
    """Strict copy-contract error with its question-relative location."""

    def __init__(self, target: str, message: str) -> None:
        super().__init__(f"{target}: {message}")
        self.target = target
        self.message = message


def normalize_questions_copy(
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return questions with canonical ``copy`` arrays for creation paths.

    Empty arrays are accepted by the core normalizer and omitted from the
    returned question object. Questions without ``copy`` are preserved.
    """
    normalize: Any | None = None
    result: list[dict[str, Any]] = []
    for question_index, raw_question in enumerate(questions):
        question = dict(raw_question)
        if "copy" not in question:
            result.append(question)
            continue
        if normalize is None:
            normalize = require_rust_binding("normalize_question_copy")
        try:
            items = normalize(question["copy"])
        except ValueError as exc:
            raise _question_copy_validation_error(question_index, exc) from exc
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise TypeError("normalize_question_copy returned a malformed result")
        if items:
            question["copy"] = [dict(item) for item in items]
        else:
            question.pop("copy", None)
        result.append(question)
    return result


def display_question_copy_items(
    question: Mapping[str, Any],
) -> QuestionCopyDisplay:
    """Read question copy metadata tolerantly for display surfaces."""
    binding = require_rust_binding("display_question_copy")
    result = binding(question.get("copy"))
    if not isinstance(result, dict):
        raise TypeError("display_question_copy returned a non-mapping")
    raw_items = result.get("items")
    unavailable = result.get("unavailable")
    if not isinstance(raw_items, list) or not isinstance(unavailable, int):
        raise TypeError("display_question_copy returned a malformed result")

    items: list[QuestionCopyItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or not isinstance(raw_item.get("text"), str):
            raise TypeError("display_question_copy returned a malformed item")
        label = raw_item.get("label")
        if label is not None and not isinstance(label, str):
            raise TypeError("display_question_copy returned a malformed label")
        items.append(QuestionCopyItem(text=raw_item["text"], label=label))
    return QuestionCopyDisplay(items=tuple(items), unavailable=unavailable)


def _question_copy_validation_error(
    question_index: int,
    error: ValueError,
) -> QuestionCopyValidationError:
    message = str(error)
    _code, separator, detail = message.partition(": ")
    if not separator:
        detail = message
    location, separator, reason = detail.partition(": ")
    if location == "copy" or location.startswith("copy["):
        target = f"question[{question_index}].{location}"
    else:
        target = f"question[{question_index}].copy"
    return QuestionCopyValidationError(target, reason if separator else detail)


__all__ = [
    "QuestionCopyDisplay",
    "QuestionCopyItem",
    "QuestionCopyValidationError",
    "display_question_copy_items",
    "normalize_questions_copy",
]

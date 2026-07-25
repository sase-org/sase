"""Typed facade over the Rust placeholder completion engine.

The extraction and completion rules live in ``sase-core`` and are shared with
the xprompt LSP.  This module only rehydrates the binding's JSON-shaped values
so TUI callers do not depend on untyped dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True, slots=True)
class PlaceholderPosition:
    """Zero-based LSP position whose character offset is measured in UTF-16."""

    line: int
    character: int


@dataclass(frozen=True, slots=True)
class PlaceholderRange:
    """Half-open range using LSP UTF-16 positions."""

    start: PlaceholderPosition
    end: PlaceholderPosition


@dataclass(frozen=True, slots=True)
class _PlaceholderCompletion:
    """Reusable placeholder candidates and their inner replacement range.

    The binding tags every candidate with the source that produced it. Until
    the TUI consumes that tag, only the candidate text is rehydrated here.
    """

    prefix: str
    replacement_range: PlaceholderRange
    append_closing_bracket: bool
    candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlaceholderSpan:
    """One complete placeholder and its full and inner ranges."""

    text: str
    range: PlaceholderRange
    inner_range: PlaceholderRange


def placeholder_completion(
    text: str,
    line: int,
    character: int,
) -> _PlaceholderCompletion | None:
    """Return completion data at an LSP position, if candidates exist."""
    binding = require_rust_binding("placeholder_completion")
    payload = binding(text, line, character)
    if payload is None:
        return None
    return _completion_from_dict(payload)


def placeholder_spans(text: str) -> tuple[PlaceholderSpan, ...]:
    """Return all complete placeholder spans in document order."""
    binding = require_rust_binding("placeholder_spans")
    return tuple(_span_from_dict(item) for item in binding(text))


def _position_from_dict(payload: dict[str, Any]) -> PlaceholderPosition:
    return PlaceholderPosition(
        line=int(payload["line"]),
        character=int(payload["character"]),
    )


def _range_from_dict(payload: dict[str, Any]) -> PlaceholderRange:
    return PlaceholderRange(
        start=_position_from_dict(payload["start"]),
        end=_position_from_dict(payload["end"]),
    )


def _completion_from_dict(payload: dict[str, Any]) -> _PlaceholderCompletion:
    return _PlaceholderCompletion(
        prefix=str(payload["prefix"]),
        replacement_range=_range_from_dict(payload["replacement_range"]),
        append_closing_bracket=bool(payload["append_closing_bracket"]),
        candidates=tuple(str(candidate["text"]) for candidate in payload["candidates"]),
    )


def _span_from_dict(payload: dict[str, Any]) -> PlaceholderSpan:
    return PlaceholderSpan(
        text=str(payload["text"]),
        range=_range_from_dict(payload["range"]),
        inner_range=_range_from_dict(payload["inner_range"]),
    )

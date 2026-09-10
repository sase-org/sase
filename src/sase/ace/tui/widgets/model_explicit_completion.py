"""Prompt ``==model`` completion backed by the shared Rust editor contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.util.editor_offsets import editor_range_to_offsets, utf16_character
from sase.ace.tui.widgets._directive_completion_models import (
    build_explicit_model_shortcut_candidates,
)
from sase.ace.tui.widgets._directive_completion_types import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets._model_shortcut_marker import (
    MODEL_EXPLICIT_SHORTCUT_MARKER,
    model_shortcut_context_payload,
    model_shortcut_edit_payload,
)
from sase.xprompt.model_completion import (
    ModelCompletionEntry,
    model_completion_entry_wire_rows,
)

MODEL_EXPLICIT_COMPLETION_KIND = "model_explicit"
MODEL_EXPLICIT_MODE_SUBTITLE = "[Enter] accept model  [Esc] normal  [^C] cancel"


@dataclass(frozen=True, slots=True)
class ModelExplicitShortcutContext:
    """ACE-facing context for a ``==model`` shortcut token."""

    query: str
    token: str
    replacement_start: int
    replacement_end: int


@dataclass(frozen=True, slots=True)
class _ModelExplicitShortcutEdit:
    """One validated edit that expands a ``==model`` shortcut."""

    replacement_start: int
    replacement_end: int
    replacement: str
    caret_offset: int


@dataclass(frozen=True, slots=True)
class _ModelExplicitCompletionPlaceholder:
    """Non-selectable loading or unavailable row for the model catalog."""

    kind: Literal["loading", "unavailable"]
    message: str


def detect_model_explicit_completion_context(
    text: str,
    cursor_location: tuple[int, int],
) -> ModelExplicitShortcutContext | None:
    """Return a Rust-classified ``==model`` context at *cursor_location*."""
    position = _editor_position(text, cursor_location)
    if position is None:
        return None
    payload = model_shortcut_context_payload(
        text,
        cursor_location,
        position,
        binding_name="model_shortcut_context",
        marker=MODEL_EXPLICIT_SHORTCUT_MARKER,
        expected_kind="model",
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("kind") != "model"
    ):
        return None
    replacement = editor_range_to_offsets(
        text,
        payload.get("replacement_range"),
        allow_empty=False,
    )
    if replacement is None:
        return None
    query = payload.get("query")
    token = payload.get("token")
    if not isinstance(query, str) or not isinstance(token, str):
        return None
    start, end = replacement
    return ModelExplicitShortcutContext(
        query=query,
        token=token,
        replacement_start=start,
        replacement_end=end,
    )


def build_model_explicit_completion_candidates(
    context: ModelExplicitShortcutContext,
    entries: Sequence[ModelCompletionEntry],
) -> list[CompletionCandidate]:
    """Build concrete-model rows for a detected shortcut context."""
    candidates, _shared = build_explicit_model_shortcut_candidates(
        context.query,
        entries,
    )
    return candidates


def build_loading_model_explicit_placeholder() -> CompletionCandidate:
    """Return the cold-catalog loading row."""
    message = "Loading models…"
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="loading",
        metadata=_ModelExplicitCompletionPlaceholder("loading", message),
    )


def build_unavailable_model_explicit_placeholder() -> CompletionCandidate:
    """Return the unavailable-catalog row."""
    message = "Models unavailable"
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="unavailable",
        metadata=_ModelExplicitCompletionPlaceholder("unavailable", message),
    )


def is_model_explicit_completion_placeholder(
    candidate: CompletionCandidate,
) -> bool:
    """Return True when *candidate* is a non-selectable status row."""
    return isinstance(candidate.metadata, _ModelExplicitCompletionPlaceholder)


def plan_model_explicit_completion_edit(
    text: str,
    cursor_location: tuple[int, int],
    entries: Sequence[ModelCompletionEntry],
    selected: CompletionCandidate,
) -> _ModelExplicitShortcutEdit | None:
    """Plan accepting *selected* through the shared Rust edit contract."""
    metadata = selected.metadata
    if not isinstance(metadata, ModelCompletionMetadata) or metadata.kind != "model":
        return None
    position = _editor_position(text, cursor_location)
    if position is None:
        return None

    payload = model_shortcut_edit_payload(
        text,
        cursor_location,
        position,
        model_completion_entry_wire_rows(entries),
        selected.insertion,
        binding_name="model_shortcut_edit",
        marker=MODEL_EXPLICIT_SHORTCUT_MARKER,
        expected_kind="model",
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("kind") != "model"
    ):
        return None
    edit = payload.get("edit")
    if not isinstance(edit, dict):
        return None
    replacement = edit.get("new_text")
    if not isinstance(replacement, str):
        return None
    edit_range = editor_range_to_offsets(
        text,
        edit.get("range"),
        allow_empty=True,
    )
    if edit_range is None:
        return None
    start, end = edit_range
    preview = f"{text[:start]}{replacement}{text[end:]}"
    caret = editor_range_to_offsets(
        preview,
        {"start": payload.get("caret"), "end": payload.get("caret")},
        allow_empty=True,
    )
    if caret is None:
        return None
    return _ModelExplicitShortcutEdit(
        replacement_start=start,
        replacement_end=end,
        replacement=replacement,
        caret_offset=caret[0],
    )


def _editor_position(
    text: str,
    location: tuple[int, int],
) -> dict[str, int] | None:
    """Convert a Textual ``(row, column)`` location to a UTF-16 editor position."""
    row, col = location
    if row < 0 or col < 0:
        return None
    lines = text.split("\n")
    if row >= len(lines):
        return None
    line = lines[row]
    col = min(col, len(line))
    return {"line": row, "character": utf16_character(line[:col])}


__all__ = [
    "MODEL_EXPLICIT_COMPLETION_KIND",
    "MODEL_EXPLICIT_MODE_SUBTITLE",
    "ModelExplicitShortcutContext",
    "build_loading_model_explicit_placeholder",
    "build_model_explicit_completion_candidates",
    "build_unavailable_model_explicit_placeholder",
    "detect_model_explicit_completion_context",
    "is_model_explicit_completion_placeholder",
    "plan_model_explicit_completion_edit",
]

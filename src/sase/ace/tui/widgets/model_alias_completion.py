"""Prompt ``*alias`` completion backed by the shared Rust editor contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.ace.tui.util.editor_offsets import editor_range_to_offsets, utf16_character
from sase.ace.tui.widgets._directive_completion_models import (
    build_model_alias_shortcut_candidates,
)
from sase.ace.tui.widgets._directive_completion_types import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.core.rust import require_rust_binding
from sase.xprompt.model_completion import (
    ModelCompletionEntry,
    model_completion_entry_wire_rows,
)

MODEL_ALIAS_COMPLETION_KIND = "model_alias"
MODEL_ALIAS_MODE_SUBTITLE = "[Enter] accept alias  [Esc] normal  [^C] cancel"
MODEL_ALIAS_ENTRY_KINDS = frozenset({"implicit_alias", "user_alias"})


@dataclass(frozen=True, slots=True)
class ModelAliasShortcutContext:
    """ACE-facing context for a ``*alias`` shortcut token."""

    query: str
    token: str
    replacement_start: int
    replacement_end: int


@dataclass(frozen=True, slots=True)
class _ModelAliasShortcutEdit:
    """One validated edit that expands a ``*alias`` shortcut."""

    replacement_start: int
    replacement_end: int
    replacement: str
    caret_offset: int


@dataclass(frozen=True, slots=True)
class _ModelAliasCompletionPlaceholder:
    """Non-selectable loading or unavailable row for the alias catalog."""

    kind: Literal["loading", "unavailable"]
    message: str


def detect_model_alias_completion_context(
    text: str,
    cursor_location: tuple[int, int],
) -> ModelAliasShortcutContext | None:
    """Return a Rust-classified ``*alias`` context at *cursor_location*."""
    position = _editor_position(text, cursor_location)
    if position is None:
        return None
    payload: Any = require_rust_binding("model_alias_shortcut_context")(
        text,
        position,
    )
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
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
    return ModelAliasShortcutContext(
        query=query,
        token=token,
        replacement_start=start,
        replacement_end=end,
    )


def build_model_alias_completion_candidates(
    context: ModelAliasShortcutContext,
    entries: Sequence[ModelCompletionEntry],
) -> list[CompletionCandidate]:
    """Build alias-only rows for a detected shortcut context."""
    candidates, _shared = build_model_alias_shortcut_candidates(
        context.query,
        entries,
    )
    return candidates


def build_loading_model_alias_placeholder() -> CompletionCandidate:
    """Return the cold-catalog loading row."""
    message = "Loading model aliases…"
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="loading",
        metadata=_ModelAliasCompletionPlaceholder("loading", message),
    )


def build_unavailable_model_alias_placeholder() -> CompletionCandidate:
    """Return the unavailable-catalog row."""
    message = "Model aliases unavailable"
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="unavailable",
        metadata=_ModelAliasCompletionPlaceholder("unavailable", message),
    )


def is_model_alias_completion_placeholder(
    candidate: CompletionCandidate,
) -> bool:
    """Return True when *candidate* is a non-selectable status row."""
    return isinstance(candidate.metadata, _ModelAliasCompletionPlaceholder)


def plan_model_alias_completion_edit(
    text: str,
    cursor_location: tuple[int, int],
    entries: Sequence[ModelCompletionEntry],
    selected: CompletionCandidate,
) -> _ModelAliasShortcutEdit | None:
    """Plan accepting *selected* through the shared Rust edit contract."""
    metadata = selected.metadata
    if (
        not isinstance(metadata, ModelCompletionMetadata)
        or metadata.kind not in MODEL_ALIAS_ENTRY_KINDS
    ):
        return None
    position = _editor_position(text, cursor_location)
    if position is None:
        return None

    payload: Any = require_rust_binding("model_alias_shortcut_edit")(
        text,
        position,
        model_completion_entry_wire_rows(entries),
        selected.insertion,
    )
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
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
    return _ModelAliasShortcutEdit(
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
    "MODEL_ALIAS_COMPLETION_KIND",
    "MODEL_ALIAS_ENTRY_KINDS",
    "MODEL_ALIAS_MODE_SUBTITLE",
    "ModelAliasShortcutContext",
    "build_loading_model_alias_placeholder",
    "build_model_alias_completion_candidates",
    "build_unavailable_model_alias_placeholder",
    "detect_model_alias_completion_context",
    "is_model_alias_completion_placeholder",
    "plan_model_alias_completion_edit",
]

"""Rust-backed argument syntax edits for prompt typing."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.util.editor_offsets import editor_range_to_offsets, utf16_character
from sase.ace.tui.widgets._paired_text_editing import TextEdit
from sase.core.rust import require_rust_binding


def plan_argument_colon_to_parentheses_edit(
    text: str,
    cursor_location: tuple[int, int],
) -> TextEdit | None:
    """Return the shared colon-deletion edit at *cursor_location*."""
    position = _editor_position(text, cursor_location)
    if position is None:
        return None
    binding = require_rust_binding("argument_colon_to_parentheses_edit")
    payload: Any = binding(text, position)
    if not isinstance(payload, dict):
        return None
    if payload.get("new_text") != "":
        return None
    edit_range = editor_range_to_offsets(
        text,
        payload.get("range"),
        allow_empty=False,
    )
    if edit_range is None:
        return None
    start, end = edit_range
    if end != start + 1 or text[start:end] != ":":
        return None
    return TextEdit(start=start, end=end, text="", cursor=start)


def _editor_position(
    text: str,
    location: tuple[int, int],
) -> dict[str, int] | None:
    """Convert a Textual ``(row, column)`` to a UTF-16 editor position."""
    row, col = location
    if row < 0 or col < 0:
        return None
    lines = text.split("\n")
    if row >= len(lines):
        return None
    line = lines[row]
    col = min(col, len(line))
    return {"line": row, "character": utf16_character(line[:col])}


__all__ = ["plan_argument_colon_to_parentheses_edit"]

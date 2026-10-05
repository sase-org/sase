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


def plan_argument_double_colon_to_parentheses_edit(
    text: str,
    cursor_location: tuple[int, int],
) -> TextEdit | None:
    """Return the shared double-colon delimiter relocation edit."""
    position = _editor_position(text, cursor_location)
    if position is None:
        return None
    binding = require_rust_binding("argument_double_colon_to_parentheses_edit")
    payload: Any = binding(text, position)
    if not isinstance(payload, dict):
        return None
    edit_range = editor_range_to_offsets(
        text,
        payload.get("range"),
        allow_empty=False,
    )
    if edit_range is None:
        return None
    start, end = edit_range
    delimiter = text[start:end]
    new_text = payload.get("new_text")
    if (
        not delimiter.startswith("::")
        or delimiter[2:] != " " * len(delimiter[2:])
        or new_text != "()" + delimiter
    ):
        return None
    return TextEdit(start=start, end=end, text=new_text, cursor=start + 1)


def plan_argument_list_continuation_edit(
    text: str,
    cursor_location: tuple[int, int],
) -> TextEdit | None:
    """Return the shared edit that continues a closed macro argument list."""
    position = _editor_position(text, cursor_location)
    if position is None:
        return None
    binding = require_rust_binding("argument_list_continuation_edit")
    payload: Any = binding(text, position)
    if not isinstance(payload, dict):
        return None
    edit_range = editor_range_to_offsets(
        text,
        payload.get("range"),
        allow_empty=True,
    )
    if edit_range is None:
        return None
    start, end = edit_range
    if end >= len(text) or text[end] != ")":
        return None
    old_text = text[start:end]
    if not old_text.isascii() or any(not char.isspace() for char in old_text):
        return None
    new_text = payload.get("new_text")
    if new_text == "":
        if start != end:
            return None
    elif new_text != "," + old_text:
        return None
    return TextEdit(
        start=start,
        end=end,
        text=new_text,
        cursor=start + len(new_text),
    )


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


def _location_from_offset(
    text: str,
    offset: int,
) -> tuple[int, int] | None:
    """Convert an absolute character offset to a ``(row, col)`` location."""
    if offset < 0 or offset > len(text):
        return None
    row = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return row, offset - line_start


def plan_macro_completion_spacer_to_parentheses_edit(
    text: str,
    cursor_location: tuple[int, int],
    pending: Any,
) -> TextEdit | None:
    """Return the shared completion-owned spacer deletion at *cursor_location*.

    *pending* is the widget's :class:`PendingMacroCompletionSpacer` recorded
    at acceptance. The Rust planner validates the exact reference, single
    ASCII space, adjacency, bounds, input eligibility, and excluded regions.
    Returns a single-character deletion edit with the cursor at its start.
    """
    try:
        spacer_offset = int(pending.spacer_offset)
        reference_start = int(pending.reference_start)
        reference_text = str(pending.reference_text)
        has_optional_inputs = bool(pending.has_optional_inputs)
    except Exception:
        return None
    position = _editor_position(text, cursor_location)
    if position is None:
        return None
    reference_location = _location_from_offset(text, reference_start)
    spacer_location = _location_from_offset(text, spacer_offset)
    if reference_location is None or spacer_location is None:
        return None
    reference_position = _editor_position(text, reference_location)
    spacer_position = _editor_position(text, spacer_location)
    if reference_position is None or spacer_position is None:
        return None
    record = {
        "reference_text": reference_text,
        "reference_start": reference_position,
        "spacer_start": spacer_position,
        "has_optional_inputs": has_optional_inputs,
    }
    binding = require_rust_binding("macro_completion_spacer_to_parentheses_edit")
    payload: Any = binding(text, position, record)
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
    if end != start + 1 or text[start:end] != " ":
        return None
    if start != spacer_offset:
        return None
    return TextEdit(start=start, end=end, text="", cursor=start)


__all__ = [
    "plan_argument_colon_to_parentheses_edit",
    "plan_argument_double_colon_to_parentheses_edit",
    "plan_argument_list_continuation_edit",
    "plan_macro_completion_spacer_to_parentheses_edit",
]

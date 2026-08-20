"""UTF-16 editor-range conversion shared by prompt overlays."""

from __future__ import annotations

from typing import Any


def editor_range_to_offsets(
    text: str,
    editor_range: Any,
    *,
    allow_empty: bool = False,
) -> tuple[int, int] | None:
    """Convert an LSP-style UTF-16 range to Python character offsets.

    Wrapped glossary/repo matches arrive as per-line segments. Each segment is
    converted independently so a multi-line term can be styled without
    including the wrapping whitespace.
    """
    if not isinstance(editor_range, dict):
        return None
    start = _editor_position_to_offset(text, editor_range.get("start"))
    end = _editor_position_to_offset(text, editor_range.get("end"))
    if start is None or end is None or end < start:
        return None
    if end == start and not allow_empty:
        return None
    return start, end


def _editor_position_to_offset(text: str, position: Any) -> int | None:
    """Convert one UTF-16 ``{line, character}`` position to a Python offset."""
    if not isinstance(position, dict):
        return None
    line = position.get("line")
    character = position.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return None
    if line < 0 or character < 0:
        return None

    row = 0
    line_start = 0
    while row < line:
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1
        row += 1

    line_end = text.find("\n", line_start)
    if line_end == -1:
        line_end = len(text)
    column = _python_column_from_utf16(text[line_start:line_end], character)
    if column is None:
        return None
    return line_start + column


def _python_column_from_utf16(line: str, character: int) -> int | None:
    """Map a UTF-16 column onto a Python index within *line*.

    A column that lands in the middle of a non-BMP code point snaps to that
    character so wrapped-term segments stay paint-able.
    """
    remaining = character
    for index, char in enumerate(line):
        width = 2 if ord(char) > 0xFFFF else 1
        if remaining == 0:
            return index
        if remaining < width:
            return index
        remaining -= width
    return len(line) if remaining == 0 else None


def utf16_character(text: str) -> int:
    """Return the UTF-16 length of *text*."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


__all__ = [
    "editor_range_to_offsets",
    "utf16_character",
]

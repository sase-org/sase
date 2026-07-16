"""Pure mapping from Rust placeholder payloads to prompt completion rows."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt.placeholder_completion import (
    PlaceholderPosition,
    PlaceholderRange,
    placeholder_completion,
)

PLACEHOLDER_COMPLETION_KIND = "placeholder"


@dataclass(frozen=True, slots=True)
class PlaceholderCompletionResult:
    """Prompt-local offsets and candidates for one placeholder context."""

    prefix: str
    replacement_start: int
    replacement_end: int
    append_closing_bracket: bool
    candidates: list[CompletionCandidate]


def build_placeholder_completion_result(
    text: str,
    cursor_offset: int,
) -> PlaceholderCompletionResult | None:
    """Return placeholder completions at a Python character offset."""
    position = _editor_position_for_offset(text, cursor_offset)
    if position is None:
        return None
    payload = placeholder_completion(
        text,
        position.line,
        position.character,
    )
    if payload is None:
        return None
    replacement = editor_range_to_offsets(text, payload.replacement_range)
    if replacement is None:
        return None
    replacement_start, replacement_end = replacement
    candidates = [
        CompletionCandidate(
            display=candidate,
            insertion=candidate,
            is_dir=False,
            name=candidate,
        )
        for candidate in payload.candidates
    ]
    if not candidates:
        return None
    return PlaceholderCompletionResult(
        prefix=payload.prefix,
        replacement_start=replacement_start,
        replacement_end=replacement_end,
        append_closing_bracket=payload.append_closing_bracket,
        candidates=candidates,
    )


def _editor_position_for_offset(
    text: str,
    offset: int,
) -> PlaceholderPosition | None:
    """Convert a Python character offset to an LSP UTF-16 position."""
    if offset < 0 or offset > len(text):
        return None
    line_start = text.rfind("\n", 0, offset) + 1
    line = text.count("\n", 0, line_start)
    character = sum(_utf16_width(char) for char in text[line_start:offset])
    return PlaceholderPosition(line=line, character=character)


def _editor_position_to_offset(
    text: str,
    position: PlaceholderPosition,
) -> int | None:
    """Convert an LSP UTF-16 position to a Python character offset."""
    if position.line < 0 or position.character < 0:
        return None
    line_start = 0
    for _ in range(position.line):
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1

    newline = text.find("\n", line_start)
    line_end = len(text) if newline == -1 else newline
    if line_end > line_start and text[line_end - 1] == "\r":
        line_end -= 1

    units = 0
    for offset, char in enumerate(text[line_start:line_end]):
        if units == position.character:
            return line_start + offset
        width = _utf16_width(char)
        if units + width > position.character:
            return None
        units += width
    if units == position.character:
        return line_end
    return None


def editor_range_to_offsets(
    text: str,
    span: PlaceholderRange,
) -> tuple[int, int] | None:
    """Convert an LSP range to Python character offsets."""
    start = _editor_position_to_offset(text, span.start)
    end = _editor_position_to_offset(text, span.end)
    if start is None or end is None or end < start:
        return None
    return start, end


def _utf16_width(char: str) -> int:
    return 2 if ord(char) > 0xFFFF else 1

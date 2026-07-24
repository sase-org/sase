"""Pure helpers for prompt hyphen-bullet ownership and structural replay."""

from __future__ import annotations

import re
from collections.abc import Sequence

__all__ = [
    "is_prompt_bullet_marker_only",
    "normalize_prompt_bullet_replay_text",
    "prompt_bullet_sibling_prefix",
]


_BULLET_MARKER_RE = re.compile(r"^( *)- ")
_FENCE_RE = re.compile(r"^ *(?:`{3,}|~{3,})")
_THEMATIC_BREAK_RE = re.compile(r"^ *(?:(?:- *){3,}|(?:\* *){3,}|(?:_ *){3,})$")
_UNSUPPORTED_MARKER_RE = re.compile(r"^ *(?:[*+] |\d+[.)] |> ?)")
_TIGHT_DASH_RE = re.compile(r"^ *-(?! )")


def _leading_space_count(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _has_tab_indentation(line: str) -> bool:
    for char in line:
        if char == "\t":
            return True
        if char != " ":
            return False
    return False


def _is_bullet_boundary(line: str) -> bool:
    """Return whether *line* stops backward hyphen-bullet ownership."""
    if not line.strip() or _has_tab_indentation(line):
        return True
    return bool(
        _FENCE_RE.match(line)
        or _THEMATIC_BREAK_RE.match(line)
        or _UNSUPPORTED_MARKER_RE.match(line)
        or _TIGHT_DASH_RE.match(line)
    )


def is_prompt_bullet_marker_only(line: str) -> bool:
    """Return whether *line* is exactly a spaces-only hyphen bullet marker."""
    return _BULLET_MARKER_RE.fullmatch(line) is not None


def normalize_prompt_bullet_replay_text(
    structural_line: str,
    replay_text: str,
) -> str:
    """Remove a replayed marker already supplied by prompt ``o`` structure.

    This covers a mutation first recorded on a plain line where the user typed
    ``- `` manually, then repeated on a line whose prompt context now supplies
    the correctly indented sibling marker automatically.
    """
    if _BULLET_MARKER_RE.fullmatch(structural_line) is None:
        return replay_text
    replay_marker = _BULLET_MARKER_RE.match(replay_text)
    if replay_marker is None:
        return replay_text
    return replay_text[replay_marker.end() :]


def prompt_bullet_sibling_prefix(
    lines: Sequence[str],
    cursor_row: int,
) -> str | None:
    """Return the containing hyphen bullet's sibling prefix at *cursor_row*.

    A direct ``- `` marker owns its line. For a physical continuation line,
    the nearest earlier marker owns it only when every intervening line stays
    at or beyond that marker's content column. Blank lines, Markdown fences,
    unsupported markers, thematic breaks, tight dashes, and tab indentation
    terminate the search.
    """
    if cursor_row < 0 or cursor_row >= len(lines):
        return None

    minimum_indent: int | None = None
    for row in range(cursor_row, -1, -1):
        line = lines[row]
        if _is_bullet_boundary(line):
            return None

        marker = _BULLET_MARKER_RE.match(line)
        marker_indent = len(marker.group(1)) if marker is not None else None
        if marker_indent is not None and (
            row == cursor_row
            or (minimum_indent is not None and minimum_indent >= marker_indent + 2)
        ):
            return f"{' ' * marker_indent}- "

        line_indent = _leading_space_count(line)
        minimum_indent = (
            line_indent if minimum_indent is None else min(minimum_indent, line_indent)
        )

    return None

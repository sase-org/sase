"""Pure helpers for prompt hyphen-bullet ownership and structural replay."""

from __future__ import annotations

import re
from collections.abc import Sequence

from sase.ace.tui.widgets._paired_text_editing import TextEdit
from sase.ace.tui.widgets._prompt_list_markers import (
    MarkerFamily,
    find_list_marker,
    is_list_boundary_line,
    list_marker_owner,
)
from sase.ace.tui.widgets._vim_transforms import INDENT_UNIT

__all__ = [
    "is_prompt_bullet_content_column",
    "is_prompt_bullet_marker_only",
    "normalize_prompt_bullet_replay_text",
    "plan_prompt_bullet_shift",
    "prompt_bullet_row_has_bullet_above",
    "prompt_bullet_sibling_prefix",
    "strip_prompt_bullet_marker",
]


_HYPHEN = MarkerFamily.HYPHEN
_BULLET_MARKER_RE = re.compile(r"^( *)- ")
_THEMATIC_BREAK_RE = re.compile(r"^ *(?:(?:- *){3,}|(?:\* *){3,}|(?:_ *){3,})$")


def is_prompt_bullet_marker_only(line: str) -> bool:
    """Return whether *line* is exactly a spaces-only hyphen bullet marker."""
    marker = find_list_marker(line, _HYPHEN)
    return marker is not None and marker.content_column == len(line)


def is_prompt_bullet_content_column(line: str, cursor_col: int) -> bool:
    """Return whether *cursor_col* is just after a supported bullet marker."""
    if is_list_boundary_line(line, _HYPHEN):
        return False
    marker = find_list_marker(line, _HYPHEN)
    return marker is not None and cursor_col == marker.content_column


def strip_prompt_bullet_marker(line: str) -> str:
    """Return *line* without a leading prompt hyphen bullet marker.

    Lines that do not open with the prompt's supported space-indented ``- ``
    marker -- tight dashes, tab indentation, unsupported markers, thematic
    breaks -- are returned unchanged.
    """
    if _THEMATIC_BREAK_RE.match(line):
        return line
    marker = find_list_marker(line, _HYPHEN)
    if marker is None:
        return line
    return line[marker.content_column :]


def plan_prompt_bullet_shift(
    text: str,
    offset: int,
    *,
    dedent: bool,
) -> TextEdit | None:
    """Plan one INSERT-mode indent or dedent of the bullet at *offset*.

    The cursor may be anywhere on the direct logical line that begins with the
    prompt's supported space-indented ``- `` marker. Indenting inserts one vim
    shift-width unit at the line start; dedenting removes up to one unit. The
    cursor follows the shifted content.
    """
    if offset < 0 or offset > len(text):
        return None

    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    marker = _BULLET_MARKER_RE.match(line)
    if marker is None:
        return None

    if not dedent:
        return TextEdit(
            start=line_start,
            end=line_start,
            text=INDENT_UNIT,
            cursor=offset + len(INDENT_UNIT),
        )

    remove_count = min(len(marker.group(1)), len(INDENT_UNIT))
    if remove_count == 0:
        return None
    return TextEdit(
        start=line_start,
        end=line_start + remove_count,
        text="",
        cursor=line_start + max(0, offset - line_start - remove_count),
    )


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
    owner = list_marker_owner(lines, cursor_row, _HYPHEN)
    return None if owner is None else owner.text


def prompt_bullet_row_has_bullet_above(
    lines: Sequence[str],
    cursor_row: int,
) -> bool:
    """Return whether the line above *cursor_row* belongs to a hyphen bullet.

    An empty marker keeps its exit-the-list behavior only when an earlier
    bullet already owns the preceding line; a lone marker instead grows one
    sibling first.
    """
    if cursor_row <= 0:
        return False
    return prompt_bullet_sibling_prefix(lines, cursor_row - 1) is not None

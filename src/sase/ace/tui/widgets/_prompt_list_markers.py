"""Shared pure primitives for prompt list markers of both families.

The prompt input widget grows two families of Markdown list markers: hyphen
bullets (``- ``) and ordered items (``<N>. `` / ``<N>) ``). Both families need
the same three questions answered -- *is this line a marker?*, *does this line
stop a marker's ownership scan?*, and *which marker owns this line?* -- so the
rules live here once and are parameterized by :class:`MarkerFamily`.

Every scan is family-scoped: a marker of the *other* family is a boundary, so
the two families never own each other's lines. All helpers are pure, do no I/O,
and scan a bounded number of lines (:data:`MAX_SCANNED_LINES`) so they stay
safe on a keystroke path.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "MAX_SCANNED_LINES",
    "ListMarker",
    "MarkerFamily",
    "find_list_marker",
    "is_list_boundary_line",
    "leading_space_count",
    "list_marker_owner",
    "owned_block_end",
]


# Upper bound on the lines any single ownership scan walks. Prompt documents
# are small; a pathological one degrades to "no owner" rather than doing
# unbounded work while the user holds a key down.
MAX_SCANNED_LINES = 2000


class MarkerFamily(Enum):
    """A family of prompt list markers."""

    HYPHEN = "hyphen"
    ORDERED = "ordered"


_HYPHEN_MARKER_RE = re.compile(r"^( *)- ")
_ORDERED_MARKER_RE = re.compile(r"^( *)(\d{1,9})([.)]) ")
# Any digit run used as a marker, including the >9-digit numbers the ordered
# family does not support. The hyphen family has always treated these as hard
# boundaries.
_ORDERED_ANY_RE = re.compile(r"^ *\d+[.)] ")
_ORDERED_LEAD_RE = re.compile(r"^ *\d+[.)]")
_DASH_LEAD_RE = re.compile(r"^ *-")
_FENCE_RE = re.compile(r"^ *(?:`{3,}|~{3,})")
_THEMATIC_BREAK_RE = re.compile(r"^ *(?:(?:- *){3,}|(?:\* *){3,}|(?:_ *){3,})$")
_BLOCKQUOTE_RE = re.compile(r"^ *> ?")
_STAR_PLUS_RE = re.compile(r"^ *[*+] ")


@dataclass(frozen=True, slots=True)
class ListMarker:
    """One list marker occurrence on a document line.

    ``content_column`` is the column the marker's content starts at, i.e. the
    column a cursor sits in immediately after the marker. ``number``,
    ``digits`` and ``delimiter`` are only meaningful for the ordered family.
    """

    row: int
    indent: int
    family: MarkerFamily
    content_column: int
    number: int = 0
    digits: str = ""
    delimiter: str = ""

    @property
    def text(self) -> str:
        """Return the marker text, including its single trailing space."""
        if self.family is MarkerFamily.HYPHEN:
            return f"{' ' * self.indent}- "
        return f"{' ' * self.indent}{self.digits}{self.delimiter} "


def leading_space_count(line: str) -> int:
    """Return the number of leading spaces on *line*."""
    return len(line) - len(line.lstrip(" "))


def _has_tab_indentation(line: str) -> bool:
    """Return whether *line* is indented with a tab."""
    for char in line:
        if char == "\t":
            return True
        if char != " ":
            return False
    return False


def find_list_marker(
    line: str,
    family: MarkerFamily,
    *,
    row: int = 0,
) -> ListMarker | None:
    """Return the *family* marker opening *line*, or ``None``.

    Extra spaces after the marker are content, not part of the marker, so only
    the single separating space is consumed.
    """
    if family is MarkerFamily.HYPHEN:
        match = _HYPHEN_MARKER_RE.match(line)
        if match is None:
            return None
        indent = len(match.group(1))
        return ListMarker(
            row=row,
            indent=indent,
            family=family,
            content_column=indent + 2,
        )

    match = _ORDERED_MARKER_RE.match(line)
    if match is None:
        return None
    indent = len(match.group(1))
    digits = match.group(2)
    return ListMarker(
        row=row,
        indent=indent,
        family=family,
        content_column=indent + len(digits) + 2,
        number=int(digits),
        digits=digits,
        delimiter=match.group(3),
    )


def is_list_boundary_line(line: str, family: MarkerFamily) -> bool:
    """Return whether *line* stops a *family* ownership scan.

    Blank lines, tab indentation, Markdown fences, thematic breaks,
    blockquotes, ``*`` / ``+`` bullets, markers of the other family, and
    "tight" markers of this family (no separating space) are all boundaries.
    """
    if not line.strip() or _has_tab_indentation(line):
        return True
    if (
        _FENCE_RE.match(line)
        or _THEMATIC_BREAK_RE.match(line)
        or _BLOCKQUOTE_RE.match(line)
        or _STAR_PLUS_RE.match(line)
    ):
        return True
    if family is MarkerFamily.HYPHEN:
        # A tight dash is not a hyphen marker, and any ordered marker belongs
        # to the other family.
        return bool(
            _ORDERED_ANY_RE.match(line)
            or (_DASH_LEAD_RE.match(line) and _HYPHEN_MARKER_RE.match(line) is None)
        )
    # Ordered family: every dash-led line belongs to the other family, and a
    # digit run that is not a supported marker (tight, or more than nine
    # digits) is a boundary rather than content.
    return bool(
        _DASH_LEAD_RE.match(line)
        or (_ORDERED_LEAD_RE.match(line) and _ORDERED_MARKER_RE.match(line) is None)
    )


def list_marker_owner(
    lines: Sequence[str],
    cursor_row: int,
    family: MarkerFamily,
) -> ListMarker | None:
    """Return the *family* marker that owns *cursor_row*, or ``None``.

    A marker owns its own line. For a physical continuation line, the nearest
    earlier marker owns it only when every intervening line stays at or beyond
    that marker's content column and no boundary line intervenes.
    """
    if cursor_row < 0 or cursor_row >= len(lines):
        return None

    minimum_indent: int | None = None
    lowest_row = max(0, cursor_row - MAX_SCANNED_LINES + 1)
    for row in range(cursor_row, lowest_row - 1, -1):
        line = lines[row]
        if is_list_boundary_line(line, family):
            return None

        marker = find_list_marker(line, family, row=row)
        if marker is not None and (
            row == cursor_row
            or (minimum_indent is not None and minimum_indent >= marker.content_column)
        ):
            return marker

        line_indent = leading_space_count(line)
        minimum_indent = (
            line_indent if minimum_indent is None else min(minimum_indent, line_indent)
        )

    return None


def owned_block_end(lines: Sequence[str], marker: ListMarker) -> int:
    """Return the last row *marker* owns (its own row when it owns nothing)."""
    last_row = marker.row
    limit = min(len(lines), marker.row + 1 + MAX_SCANNED_LINES)
    for row in range(marker.row + 1, limit):
        line = lines[row]
        if is_list_boundary_line(line, marker.family):
            break
        if leading_space_count(line) < marker.content_column:
            break
        last_row = row
    return last_row

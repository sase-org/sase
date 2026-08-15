"""INSERT-mode ``Tab`` / ``Shift+Tab`` nesting for prompt ordered items.

Hyphen bullets shift by a fixed two-space unit, which is all they need: for
``- `` the content column *is* two. Ordered markers are wider and variable, so
nesting has to move an item to its parent's *content column* instead. That is
required rather than cosmetic -- a ``2. `` item indented two spaces under a
``1. `` parent is still a sibling to CommonMark, and an ordered item can only
interrupt a parent's paragraph when it is numbered ``1``.

So a ``Tab`` that starts a new nested list numbers the moved item ``1``, a
``Tab`` that lands under an existing nested run continues that run, and
``Shift+Tab`` moves the item out to its parent's indent and takes the next
number of the enclosing run. Both carry the item's owned block along and
renumber the run the item left as well as the run it joined, all as one
:class:`TextEdit` so a keypress stays a single undo checkpoint.
"""

from __future__ import annotations

from collections.abc import Sequence

from sase.ace.tui.widgets._paired_text_editing import TextEdit
from sase.ace.tui.widgets._prompt_list_markers import (
    ListMarker,
    MarkerFamily,
    find_list_marker,
    is_list_boundary_line,
    leading_space_count,
    owned_block_end,
)
from sase.ace.tui.widgets._prompt_ordered_editing import (
    MAX_ORDERED_SCAN_LINES,
    find_ordered_run,
    plan_ordered_list_edit,
)

__all__ = ["plan_prompt_ordered_shift"]


_HYPHEN = MarkerFamily.HYPHEN
_ORDERED = MarkerFamily.ORDERED


def plan_prompt_ordered_shift(
    text: str,
    offset: int,
    *,
    dedent: bool,
) -> TextEdit | None:
    """Plan one INSERT-mode nest or unnest of the ordered item at *offset*.

    Returns ``None`` -- leaving the caller's other ``Tab`` handling to run --
    when the cursor line is not a supported ordered marker line or when the
    move is a no-op (nothing to nest under, or already at the outermost level).
    Any cursor offset on the direct marker line is eligible.
    """
    if offset < 0 or offset > len(text):
        return None

    lines = text.split("\n")
    line_start = text.rfind("\n", 0, offset) + 1
    cursor_row = text.count("\n", 0, line_start)
    cursor_col = offset - line_start

    item = find_list_marker(lines[cursor_row], _ORDERED, row=cursor_row)
    if item is None:
        return None

    parent = _nesting_parent(
        lines,
        item,
        max_indent=item.indent - 1 if dedent else item.indent,
    )
    if parent is None:
        return None

    target_indent = parent.indent if dedent else parent.content_column
    if target_indent == item.indent:
        return None

    shifted = _shift_item_block(lines, item, target_indent - item.indent)
    moved = find_list_marker(shifted[cursor_row], _ORDERED, row=cursor_row)
    if moved is None:
        return None

    numbered = list(shifted)
    number = _destination_number(shifted, moved)
    marker_text = f"{' ' * moved.indent}{number}{moved.delimiter} "
    numbered[cursor_row] = marker_text + shifted[cursor_row][moved.content_column :]

    anchor_rows = [cursor_row]
    source_row = _preceding_sibling_row(numbered, cursor_row, item)
    if source_row is not None:
        anchor_rows.append(source_row)

    new_content_column = len(marker_text)
    return plan_ordered_list_edit(
        text,
        numbered,
        anchor_rows=anchor_rows,
        cursor_row=cursor_row,
        cursor_col=max(0, cursor_col + new_content_column - item.content_column),
    )


def _nesting_parent(
    lines: Sequence[str],
    item: ListMarker,
    *,
    max_indent: int,
) -> ListMarker | None:
    """Return the marker *item* nests under, or ``None``.

    The parent is the nearest preceding marker line of *either* family whose
    indent is at most *max_indent*; deeper markers belong to a nested list and
    are skipped. Blank lines are transparent, but a construct that breaks both
    families -- a fence, a blockquote, a thematic break, a ``*`` / ``+`` bullet,
    tab indentation -- or prose at *item*'s own level ends the search.
    """
    scanned = 0
    row = item.row - 1
    while row >= 0 and scanned < MAX_ORDERED_SCAN_LINES:
        scanned += 1
        line = lines[row]
        if not line.strip():
            row -= 1
            continue
        marker = find_list_marker(line, _HYPHEN, row=row) or find_list_marker(
            line, _ORDERED, row=row
        )
        if marker is not None:
            if marker.indent <= max_indent:
                return marker
            row -= 1
            continue
        if is_list_boundary_line(line, _HYPHEN) and is_list_boundary_line(
            line, _ORDERED
        ):
            return None
        if leading_space_count(line) <= item.indent:
            return None
        row -= 1
    return None


def _shift_item_block(
    lines: Sequence[str],
    item: ListMarker,
    delta: int,
) -> list[str]:
    """Return *lines* with *item* and the block it owns shifted by *delta*."""
    shifted = list(lines)
    block_end = owned_block_end(lines, item)
    for row in range(item.row, block_end + 1):
        line = shifted[row]
        if delta > 0:
            shifted[row] = " " * delta + line
            continue
        removed = min(leading_space_count(line), -delta)
        if removed:
            shifted[row] = line[removed:]
    return shifted


def _destination_number(lines: Sequence[str], moved: ListMarker) -> int:
    """Return the number *moved* takes in the run it just joined.

    An item that lands after a sibling continues that run; one that starts a
    new nested list -- or heads its new run -- is numbered ``1``. The renumber
    pass then normalizes the whole run, so this only has to pick the slot.
    """
    run = find_ordered_run(lines, moved.row)
    index = None if run is None else run.index_of(moved.row)
    if run is None or index is None or index == 0:
        return 1
    return run.items[index - 1].number + 1


def _preceding_sibling_row(
    lines: Sequence[str],
    row: int,
    item: ListMarker,
) -> int | None:
    """Return the row of the item that now precedes the hole *item* left.

    That item anchors the *source* run, so the gap the move opened is closed by
    the same edit. ``None`` means the moved item had no earlier sibling and the
    source run therefore needs no renumbering.
    """
    scanned = 0
    candidate = row - 1
    while candidate >= 0 and scanned < MAX_ORDERED_SCAN_LINES:
        scanned += 1
        line = lines[candidate]
        if not line.strip():
            candidate -= 1
            continue
        marker = find_list_marker(line, _ORDERED, row=candidate)
        if (
            marker is not None
            and marker.indent == item.indent
            and marker.delimiter == item.delimiter
        ):
            return candidate
        if is_list_boundary_line(line, _ORDERED):
            return None
        if leading_space_count(line) <= item.indent:
            return None
        candidate -= 1
    return None

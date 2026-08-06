"""Pure helpers for prompt ordered-list ownership, numbering, and planning.

Ordered items (``<N>. `` / ``<N>) ``) mirror every rule the hyphen bullets in
:mod:`_prompt_bullet_editing` already follow -- both are built on the shared
primitives in :mod:`_prompt_list_markers` -- and add the one thing ordered
lists need: the surrounding *run* is renumbered after every structural edit so
live numbering always agrees with what the prompt formatter (Prettier) would
produce.

A **run** is the maximal sequence of ordered items sharing the same indent and
the same delimiter, joined only by lines an earlier item owns or by blank
lines. Numbering reproduces Prettier's own rule: when the run's *second* item is
numbered ``1`` the run is in Prettier's "git diff friendly" *repeat style*, so
the first item keeps its number and every later item stays ``1``; otherwise the
run is *sequential* and item *i* is ``first_number + i``.

Structural keymaps do not mutate the document directly. Each one has a planner
(:func:`plan_ordered_insert_newline` for INSERT-mode ``Ctrl+J``) that builds
the changed lines and hands them to :func:`plan_ordered_list_edit`, which
renumbers the run the change restructured and returns a single
:class:`TextEdit` -- one keypress stays one undo checkpoint, because Textual
opens a new undo batch for every multi-character edit. A planner returns
``None`` when no ordered item is involved, leaving the hyphen path untouched.

Everything here is pure, does no I/O, and is bounded: a run larger than
:data:`MAX_ORDERED_RUN_ITEMS` (or a scan longer than
:data:`MAX_ORDERED_SCAN_LINES`) silently skips renumbering instead of doing
unbounded work on a keystroke.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sase.ace.tui.widgets._paired_text_editing import TextEdit
from sase.ace.tui.widgets._prompt_list_markers import (
    ListMarker,
    MarkerFamily,
    find_list_marker,
    is_list_boundary_line,
    leading_space_count,
    list_marker_owner,
    owned_block_end,
)

__all__ = [
    "MAX_ORDERED_RUN_ITEMS",
    "MAX_ORDERED_SCAN_LINES",
    "find_ordered_run",
    "plan_ordered_insert_newline",
    "plan_ordered_list_edit",
    "strip_prompt_ordered_marker",
]


# Bounds for one keystroke's worth of work. Exceeding either one degrades to
# "do the structural edit, skip the renumber" -- silently, with no notification.
MAX_ORDERED_RUN_ITEMS = 400
MAX_ORDERED_SCAN_LINES = 2000

_ORDERED = MarkerFamily.ORDERED


@dataclass(frozen=True, slots=True)
class _OrderedRun:
    """One maximal run of sibling ordered items."""

    items: tuple[ListMarker, ...]
    oversized: bool = False

    @property
    def repeat_style(self) -> bool:
        """Return whether the run uses Prettier's "git diff friendly" style.

        Prettier detects that style from the *second* item being numbered ``1``
        -- the ``1. / 1. / 1.`` convention -- and then keeps every item after
        the first at ``1``. A run starting at ``0`` needs its third item to
        agree too, mirroring Prettier's own special case.
        """
        if len(self.items) < 2:
            return False
        if self.items[0].number == 0 and len(self.items) > 2:
            return self.items[1].number == 1 and self.items[2].number == 1
        return self.items[1].number == 1

    def index_of(self, row: int) -> int | None:
        """Return the position of the item whose marker sits on *row*."""
        for index, item in enumerate(self.items):
            if item.row == row:
                return index
        return None

    def number_at(self, index: int) -> int:
        """Return the number item *index* should carry after renumbering.

        *index* may point one past the end, which is how an about-to-be
        inserted sibling asks for its own number.
        """
        first = self.items[0].number
        if not self.repeat_style:
            return first + index
        return first if index == 0 else 1


@dataclass(frozen=True, slots=True)
class _LineShift:
    """How a renumber pass changed the start of one line."""

    prefix_length: int
    delta: int


@dataclass(frozen=True, slots=True)
class _RenumberResult:
    """The renumbered lines plus the column shifts the pass introduced."""

    lines: list[str]
    shifts: dict[int, _LineShift] = field(default_factory=dict)

    def adjust_column(self, row: int, column: int) -> int:
        """Return *column* on *row* translated into the renumbered lines."""
        shift = self.shifts.get(row)
        if shift is None:
            return column
        if column >= shift.prefix_length:
            return max(0, column + shift.delta)
        return max(0, min(column, shift.prefix_length + shift.delta))


def _is_prompt_ordered_marker_only(line: str) -> bool:
    """Return whether *line* is exactly a spaces-only ordered marker."""
    marker = find_list_marker(line, _ORDERED)
    return marker is not None and marker.content_column == len(line)


def _is_prompt_ordered_content_column(line: str, cursor_col: int) -> bool:
    """Return whether *cursor_col* is just after an ordered marker."""
    if is_list_boundary_line(line, _ORDERED):
        return False
    marker = find_list_marker(line, _ORDERED)
    return marker is not None and cursor_col == marker.content_column


def strip_prompt_ordered_marker(line: str) -> str:
    """Return *line* without a leading ordered marker.

    Lines that do not open with a supported space-indented ordered marker are
    returned unchanged.
    """
    if is_list_boundary_line(line, _ORDERED):
        return line
    marker = find_list_marker(line, _ORDERED)
    if marker is None:
        return line
    return line[marker.content_column :]


def _prompt_ordered_row_has_item_above(lines: Sequence[str], cursor_row: int) -> bool:
    """Return whether the line above *cursor_row* belongs to an ordered item."""
    if cursor_row <= 0:
        return False
    return list_marker_owner(lines, cursor_row - 1, _ORDERED) is not None


def _previous_sibling(lines: Sequence[str], item: ListMarker) -> ListMarker | None:
    """Return the ordered item immediately preceding *item* in its run."""
    minimum_indent: int | None = None
    row = item.row - 1
    scanned = 0
    while row >= 0 and scanned < MAX_ORDERED_SCAN_LINES:
        scanned += 1
        line = lines[row]
        if not line.strip():
            # Blank lines are transparent: a loose list is still one list.
            row -= 1
            continue
        if is_list_boundary_line(line, _ORDERED):
            return None
        marker = find_list_marker(line, _ORDERED, row=row)
        if (
            marker is not None
            and marker.indent == item.indent
            and marker.delimiter == item.delimiter
        ):
            if minimum_indent is None or minimum_indent >= marker.content_column:
                return marker
            return None
        indent = leading_space_count(line)
        if indent <= item.indent:
            # Prose (or a shallower marker) at the run's own level ends the run.
            return None
        minimum_indent = (
            indent if minimum_indent is None else min(minimum_indent, indent)
        )
        row -= 1
    return None


def _next_sibling(lines: Sequence[str], item: ListMarker) -> ListMarker | None:
    """Return the ordered item immediately following *item* in its run."""
    minimum_indent: int | None = None
    row = item.row + 1
    scanned = 0
    while row < len(lines) and scanned < MAX_ORDERED_SCAN_LINES:
        scanned += 1
        line = lines[row]
        if not line.strip():
            row += 1
            continue
        if is_list_boundary_line(line, _ORDERED):
            return None
        marker = find_list_marker(line, _ORDERED, row=row)
        if (
            marker is not None
            and marker.indent == item.indent
            and marker.delimiter == item.delimiter
        ):
            if minimum_indent is None or minimum_indent >= item.content_column:
                return marker
            return None
        indent = leading_space_count(line)
        if indent <= item.indent:
            return None
        minimum_indent = (
            indent if minimum_indent is None else min(minimum_indent, indent)
        )
        row += 1
    return None


def find_ordered_run(lines: Sequence[str], row: int) -> _OrderedRun | None:
    """Return the ordered run containing *row*, or ``None``.

    *row* may be an item's marker line or any line that item owns.
    """
    anchor = list_marker_owner(lines, row, _ORDERED)
    if anchor is None:
        return None

    oversized = False
    before: list[ListMarker] = []
    item = anchor
    while (previous := _previous_sibling(lines, item)) is not None:
        before.append(previous)
        item = previous
        if len(before) >= MAX_ORDERED_RUN_ITEMS:
            oversized = True
            break

    after: list[ListMarker] = []
    item = anchor
    while (following := _next_sibling(lines, item)) is not None:
        after.append(following)
        item = following
        if len(after) >= MAX_ORDERED_RUN_ITEMS:
            oversized = True
            break

    items = tuple(reversed(before)) + (anchor,) + tuple(after)
    if len(items) > MAX_ORDERED_RUN_ITEMS:
        oversized = True
    return _OrderedRun(items=items, oversized=oversized)


def _prompt_ordered_sibling_prefix(
    lines: Sequence[str],
    cursor_row: int,
    *,
    increment: bool = True,
) -> str | None:
    """Return the marker a new ordered sibling at *cursor_row* should carry.

    The new item takes the number the run's numbering rule gives the slot it
    lands in: after its owner by default, or in the owner's own slot when it
    lands *before* it (``O`` on a marker row, ``increment=False``). Indent and
    delimiter are copied from the owning item.
    """
    owner = list_marker_owner(lines, cursor_row, _ORDERED)
    if owner is None:
        return None

    run = find_ordered_run(lines, owner.row)
    index = None if run is None else run.index_of(owner.row)
    if run is None or index is None:
        number = owner.number + (1 if increment else 0)
    else:
        number = run.number_at(index + (1 if increment else 0))
    return f"{' ' * owner.indent}{number}{owner.delimiter} "


def _record_shift(
    shifts: dict[int, _LineShift],
    row: int,
    prefix_length: int,
    delta: int,
) -> None:
    existing = shifts.get(row)
    if existing is None:
        shifts[row] = _LineShift(prefix_length=prefix_length, delta=delta)
        return
    shifts[row] = _LineShift(
        prefix_length=existing.prefix_length,
        delta=existing.delta + delta,
    )


def _renumber_ordered_runs(
    lines: Sequence[str],
    anchor_rows: Iterable[int],
) -> _RenumberResult:
    """Renumber the run containing each row in *anchor_rows*.

    Runs are renumbered in place over a copy of *lines*; the line count never
    changes. When an item's marker width changes (``9.`` -> ``10.``) every line
    that item owns is shifted by the same delta so ownership and the
    formatter's indentation both stay correct. Oversized runs are left alone.
    """
    working = list(lines)
    shifts: dict[int, _LineShift] = {}
    renumbered_starts: set[int] = set()

    for anchor_row in anchor_rows:
        run = find_ordered_run(working, anchor_row)
        if run is None or run.oversized:
            continue
        if run.items[0].row in renumbered_starts:
            continue
        renumbered_starts.add(run.items[0].row)

        for index, item in enumerate(run.items):
            number = run.number_at(index)
            digits = str(number)
            if digits == item.digits:
                continue
            marker_text = f"{' ' * item.indent}{digits}{item.delimiter} "
            delta = len(marker_text) - item.content_column
            block_end = owned_block_end(working, item)
            working[item.row] = marker_text + working[item.row][item.content_column :]
            _record_shift(shifts, item.row, item.content_column, delta)
            if delta == 0:
                continue
            for row in range(item.row + 1, block_end + 1):
                line = working[row]
                indent = leading_space_count(line)
                if delta > 0:
                    working[row] = " " * delta + line
                    _record_shift(shifts, row, indent, delta)
                    continue
                removed = min(indent, -delta)
                if removed:
                    working[row] = line[removed:]
                    _record_shift(shifts, row, indent, -removed)

    return _RenumberResult(lines=working, shifts=shifts)


def _plan_list_text_edit(
    text: str,
    new_lines: Sequence[str],
    cursor_row: int,
    cursor_col: int,
) -> TextEdit | None:
    """Return the single :class:`TextEdit` turning *text* into *new_lines*.

    The edit spans the minimal contiguous range of changed rows. The cursor is
    the absolute offset of ``(cursor_row, cursor_col)`` in the *rebuilt* text,
    never offset arithmetic on the original -- renumbering can change the width
    of lines above the edit.
    """
    old_lines = text.split("\n")
    new = list(new_lines)
    if old_lines == new:
        return None

    prefix = 0
    while (
        prefix < len(old_lines)
        and prefix < len(new)
        and old_lines[prefix] == new[prefix]
    ):
        prefix += 1

    suffix = 0
    while (
        suffix < len(old_lines) - prefix
        and suffix < len(new) - prefix
        and old_lines[len(old_lines) - 1 - suffix] == new[len(new) - 1 - suffix]
    ):
        suffix += 1

    old_start = prefix
    old_end = len(old_lines) - suffix
    new_start = prefix
    new_end = len(new) - suffix
    if old_start == old_end or new_start == new_end:
        # A pure line insertion or deletion: widen the range by one shared row
        # so the replacement covers real text -- and its newline -- rather
        # than a bare seam.
        if old_start > 0 and new_start > 0:
            old_start -= 1
            new_start -= 1
        else:
            old_end = min(old_end + 1, len(old_lines))
            new_end = min(new_end + 1, len(new))

    row_offsets = _row_offsets(old_lines)
    start = row_offsets[old_start]
    end = row_offsets[old_end - 1] + len(old_lines[old_end - 1])

    new_offsets = _row_offsets(new)
    cursor_row = max(0, min(cursor_row, len(new) - 1))
    cursor = new_offsets[cursor_row] + max(0, min(cursor_col, len(new[cursor_row])))
    return TextEdit(
        start=start,
        end=end,
        text="\n".join(new[new_start:new_end]),
        cursor=cursor,
    )


def plan_ordered_list_edit(
    text: str,
    new_lines: Sequence[str],
    *,
    anchor_rows: Iterable[int],
    cursor_row: int,
    cursor_col: int,
) -> TextEdit | None:
    """Renumber *new_lines* around *anchor_rows* and plan one text edit.

    *new_lines* is the document after the caller's structural change only;
    ``anchor_rows`` are rows in those lines whose runs the change restructured.
    The cursor location is given in the same structurally-edited coordinates
    and is translated across any marker-width change the renumber pass makes.
    Returns ``None`` when the plan would leave *text* unchanged.
    """
    result = _renumber_ordered_runs(new_lines, anchor_rows)
    return _plan_list_text_edit(
        text,
        result.lines,
        cursor_row,
        result.adjust_column(cursor_row, cursor_col),
    )


def _previous_sibling_row(lines: Sequence[str], row: int) -> int | None:
    """Return the row of the ordered item preceding the item on *row*."""
    item = find_list_marker(lines[row], _ORDERED, row=row)
    if item is None:
        return None
    previous = _previous_sibling(lines, item)
    return None if previous is None else previous.row


def _anchor_rows(anchor: int | None) -> tuple[int, ...]:
    """Return the anchor tuple for a removal path with an optional anchor."""
    return () if anchor is None else (anchor,)


def _plan_ordered_marker_exit(
    text: str,
    lines: Sequence[str],
    row: int,
) -> TextEdit | None:
    """Plan the list exit from an empty ordered marker on *row*."""
    new_lines = list(lines)
    new_lines[row] = ""
    new_lines.insert(row + 1, "")
    return plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=_anchor_rows(_previous_sibling_row(lines, row)),
        cursor_row=row + 1,
        cursor_col=0,
    )


def _plan_ordered_grow_sibling(
    text: str,
    lines: Sequence[str],
    row: int,
) -> TextEdit | None:
    """Plan the sibling a lone ordered marker on *row* grows below itself."""
    prefix = _prompt_ordered_sibling_prefix(lines, row)
    if prefix is None:
        return None
    new_lines = list(lines)
    new_lines.insert(row + 1, prefix)
    return plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(row + 1,),
        cursor_row=row + 1,
        cursor_col=len(prefix),
    )


def _plan_ordered_delist(
    text: str,
    lines: Sequence[str],
    row: int,
) -> TextEdit | None:
    """Plan dropping the marker of the populated ordered item on *row*."""
    item = find_list_marker(lines[row], _ORDERED, row=row)
    if item is None:
        return None
    new_lines = list(lines)
    new_lines[row] = ""
    new_lines.insert(row + 1, lines[row][item.content_column :])
    return plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=_anchor_rows(_previous_sibling_row(lines, row)),
        cursor_row=row + 1,
        cursor_col=0,
    )


def _plan_ordered_split(
    text: str,
    lines: Sequence[str],
    start: tuple[int, int],
    end: tuple[int, int],
    prefix_row: int,
) -> TextEdit | None:
    """Plan the split of an ordered item at (or across) the selection."""
    prefix = _prompt_ordered_sibling_prefix(lines, prefix_row)
    if prefix is None:
        return None
    (top_row, top_col), (bottom_row, bottom_col) = sorted((start, end))
    head = lines[top_row][: max(0, top_col)]
    tail = lines[bottom_row][max(0, bottom_col) :]
    new_lines = [*lines[:top_row], head, prefix + tail, *lines[bottom_row + 1 :]]
    return plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(top_row + 1,),
        cursor_row=top_row + 1,
        cursor_col=len(prefix),
    )


def plan_ordered_insert_newline(
    lines: Sequence[str],
    start: tuple[int, int],
    end: tuple[int, int],
) -> TextEdit | None:
    """Plan one INSERT-mode ``Ctrl+J`` press inside an ordered list.

    Mirrors the hyphen ``Ctrl+J`` rules -- split at the cursor, exit from an
    empty marker (growing one sibling first when no ordered item sits above),
    de-list at the content column, and replace an active selection -- and adds
    the renumber of the one run the press restructured. *start* and *end* are
    the selection's endpoints; *end* is the cursor, and its row selects the
    owning item exactly as the hyphen path does. Returns ``None`` when no
    ordered item is involved, leaving the hyphen path to run unchanged.
    """
    row = end[0]
    if row < 0 or row >= len(lines):
        return None
    line = lines[row]
    if (
        not _is_prompt_ordered_marker_only(line)
        and list_marker_owner(lines, row, _ORDERED) is None
    ):
        # Cheap early-out before joining the document: nothing here is ordered.
        return None

    text = "\n".join(lines)
    if start == end:
        if _is_prompt_ordered_marker_only(line):
            if _prompt_ordered_row_has_item_above(lines, row):
                return _plan_ordered_marker_exit(text, lines, row)
            return _plan_ordered_grow_sibling(text, lines, row)
        if _is_prompt_ordered_content_column(
            line, start[1]
        ) and _prompt_ordered_row_has_item_above(lines, row):
            return _plan_ordered_delist(text, lines, row)

    return _plan_ordered_split(text, lines, start, end, row)


def _row_offsets(lines: Sequence[str]) -> list[int]:
    offsets: list[int] = []
    running = 0
    for line in lines:
        offsets.append(running)
        running += len(line) + 1
    return offsets

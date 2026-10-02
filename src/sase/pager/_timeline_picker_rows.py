"""Column fitting for the ``@`` timeline picker rows.

Pure and Textual-free: this module owns the picker column widths and
row formatting the pager timeline modal lays out, so ACE lenses can
reuse the pager's exact cells through
:mod:`sase.pager.history_kit` (epic design
``plan:202610/memory_history_tui.md`` §5.3). Shedding order as width
shrinks: the SHA, then attribution, then the age.

Moved verbatim out of :mod:`sase.pager._timeline_picker`, which
imports the public names from here; pager picker goldens stay
byte-identical.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from rich.text import Text

#: Attribution column cap and the smallest flex width worth keeping.
_BY_WIDTH_CAP = 24
_CHANGE_MIN_WIDTH = 8
_NOW_ALIAS_SUFFIX = "≡ now"

#: Two-cell marker column: the open row carries ``●``, the cursor row
#: carries ``▸``, and both show when the cursor sits on the open row.
_MARKER_OPEN = "●"
_MARKER_CURSOR = "▸"


def _truncate_cell(value: str, width: int) -> str:
    """Truncate *value* to *width* cells with an ellipsis."""
    if cell_len(value) <= width:
        return value
    if width <= 0:
        return ""
    if width == 1:
        return "…"
    budget = width - 1
    kept: list[str] = []
    used = 0
    for character in value:
        char_width = cell_len(character)
        if used + char_width > budget:
            break
        kept.append(character)
        used += char_width
    return "".join(kept) + "…"


@dataclass(frozen=True, slots=True)
class PickerColumns:
    """Fitted column widths for one picker render."""

    available: int
    label_w: int
    date_w: int
    age_w: int
    by_w: int
    show_sha: bool
    show_by: bool
    show_age: bool
    change_w: int


def picker_columns(
    rows: tuple[Mapping[str, Any], ...], available: int
) -> PickerColumns:
    """Fit picker columns to *available* cells (never wrapping).

    Shedding order as width shrinks: the SHA, then attribution, then
    the age. The change column flexes into whatever remains.
    """
    width = max(int(available or 0), 0)
    label_w = 3
    date_w = 0
    age_w = 0
    by_w = 0
    for row in rows:
        label_w = max(label_w, cell_len(str(row.get("label", "") or "")))
        date_w = max(date_w, cell_len(str(row.get("date", "") or "")))
        age_w = max(age_w, cell_len(str(row.get("age", "") or "")))
        if not bool(row.get("pseudo", False)):
            by_w = max(by_w, cell_len(str(row.get("by", "") or "")))
    by_w = min(by_w, _BY_WIDTH_CAP)
    show_sha = True
    show_by = by_w > 0
    show_age = age_w > 0
    while True:
        fixed = 2 + label_w + 2 + 1 + 2
        if date_w:
            fixed += date_w + 2
        if show_age:
            fixed += age_w + 2
        if show_by:
            fixed += by_w + 2
        if show_sha:
            fixed += 7 + 2
        change_w = width - fixed
        if change_w >= _CHANGE_MIN_WIDTH:
            break
        if show_sha:
            show_sha = False
        elif show_by:
            show_by = False
        elif show_age:
            show_age = False
        else:
            change_w = max(change_w, 0)
            break
    return PickerColumns(
        available=width,
        label_w=label_w,
        date_w=date_w,
        age_w=age_w,
        by_w=by_w,
        show_sha=show_sha,
        show_by=show_by,
        show_age=show_age,
        change_w=max(change_w, 0),
    )


def format_picker_row(
    row: Mapping[str, Any],
    columns: PickerColumns,
    *,
    is_open: bool,
    is_cursor: bool,
    open_style: str | None = None,
) -> Text:
    """Format one picker row as a single non-wrapping line."""
    marker = f"{_MARKER_OPEN if is_open else ' '}{_MARKER_CURSOR if is_cursor else ' '}"
    label = str(row.get("label", "") or "")
    hidden = bool(row.get("hidden", False))
    line = Text()
    line.append(marker)
    padded = label.rjust(columns.label_w - (cell_len(label) - len(label)))
    # Right-align the label to the widest label (cell-aware).
    while cell_len(padded) < columns.label_w:
        padded = " " + padded
    if is_open and not is_cursor and open_style:
        line.append(padded, style=open_style)
    else:
        line.append(padded)
    line.append("  ")
    if bool(row.get("pseudo", False)):
        glyph = str(row.get("glyph", "") or "")
        detail = str(row.get("detail", "") or "")
        budget = max(columns.available - cell_len(line.plain) - 2 - 1, 0)
        line.append(glyph)
        line.append("  ")
        line.append(_truncate_cell(detail, budget))
        return line
    if columns.date_w:
        date = _truncate_cell(str(row.get("date", "") or ""), columns.date_w)
        line.append(date + " " * (columns.date_w - cell_len(date)))
        line.append("  ")
    if columns.show_age:
        age = _truncate_cell(str(row.get("age", "") or ""), columns.age_w)
        line.append(age + " " * (columns.age_w - cell_len(age)))
        line.append("  ")
    line.append(str(row.get("glyph", "") or ""))
    line.append("  ")
    change = str(row.get("change", "") or "")
    words = str(row.get("words", "") or "")
    change_text = f"{change} {words}".strip() if words else change
    if bool(row.get("is_now_alias", False)):
        suffix = f"  {_NOW_ALIAS_SUFFIX}"
        change_budget = max(columns.change_w - cell_len(suffix), 0)
        line.append(_truncate_cell(change_text, change_budget))
        line.append(suffix, style="dim")
    else:
        line.append(_truncate_cell(change_text, columns.change_w))
        line.append(" " * max(columns.change_w - cell_len(change_text), 0))
    if columns.show_by:
        by = _truncate_cell(str(row.get("by", "") or ""), columns.by_w)
        line.append("  ")
        line.append(by + " " * max(columns.by_w - cell_len(by), 0))
    if columns.show_sha:
        line.append("  ")
        line.append(str(row.get("sha", "") or "")[:7])
    if hidden and not is_cursor:
        line.stylize("dim")
    return line


__all__ = [
    "PickerColumns",
    "format_picker_row",
    "picker_columns",
]

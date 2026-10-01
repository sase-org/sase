"""The ``@`` timeline picker modal for pager history sections.

List mode only: ``j``/``k``/``g``/``G`` move, ``⏎`` opens the
highlighted version (pushing a trail entry), ``=`` compares it with
the open version, ``.`` toggles hidden versions, ``/`` filters across
section, agent, bead, and words, and ``esc`` closes. Rows are generic
mappings (``ordinal``, ``class``, ``label``, ``display``,
``haystack``, ``hidden``) so this module never imports memory code;
only one window of rows is composed per keypress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.pager._styles import PAGER_CSS
from sase.pager.history.timeline import filter_rows, picker_window, visible_rows

#: Rows composed per render around the cursor; the full row list is
#: kept as cheap mappings so large timelines stay instant.
_PICKER_WINDOW_HEIGHT = 20

#: Style for the cursor line and for the open version's row. The
#: caller overrides the open style with the theme-aware moment colour.
_CURSOR_STYLE = "reverse"
_CURRENT_STYLE = "#9d7cd8"

_PICKER_FOOTER = (
    "⏎ open · = compare with open version · . hidden · / filter · esc close"
)

#: Two-cell marker column: the open row carries ``●``, the cursor row
#: carries ``▸``, and both show when the cursor sits on the open row.
_MARKER_OPEN = "●"
_MARKER_CURSOR = "▸"

#: Attribution column cap and the smallest flex width worth keeping.
_BY_WIDTH_CAP = 24
_CHANGE_MIN_WIDTH = 8
_NOW_ALIAS_SUFFIX = "≡ now"


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
class _PickerColumns:
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


def _picker_columns(
    rows: tuple[Mapping[str, Any], ...], available: int
) -> _PickerColumns:
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
    return _PickerColumns(
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


def _format_picker_row(
    row: Mapping[str, Any],
    columns: _PickerColumns,
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


class TimelinePickerScreen(ModalScreen[dict[str, Any] | None]):
    """Modal timeline over one section's versions."""

    CSS = PAGER_CSS

    BINDINGS = [
        Binding("j,down", "picker_down", "Down", show=False),
        Binding("k,up", "picker_up", "Up", show=False),
        Binding("g", "picker_top", "Top", show=False),
        Binding("G", "picker_bottom", "Bottom", show=False),
        Binding("enter", "picker_open", "Open", show=False),
        Binding("equals_sign", "picker_compare", "Compare", show=False),
        Binding("full_stop", "picker_hidden", "Hidden", show=False),
        Binding("slash", "picker_filter", "Filter", show=False),
        Binding("escape", "picker_escape", "Close", show=False),
    ]

    def __init__(
        self,
        *,
        title: str,
        rows: tuple[Mapping[str, Any], ...],
        current_ordinal: int,
        current_class: str,
        hidden_summary: str = "",
        show_hidden: bool = False,
        initial_cursor: int = 0,
        open_style: str = _CURRENT_STYLE,
    ) -> None:
        super().__init__()
        self._title = title
        # The caller bakes a ``— / filter`` suffix into the title; the
        # modal re-renders that suffix live from its own query state.
        self._base_title = title.split(" — / ")[0] if " — / " in title else title
        self._all_rows = rows
        self._current_ordinal = current_ordinal
        self._current_class = current_class
        self._hidden_summary = hidden_summary
        self._show_hidden = show_hidden
        self._open_style = open_style or _CURRENT_STYLE
        self._query = ""
        self._filtering = False
        self._draft = ""
        self._cursor = max(0, int(initial_cursor))
        self._clamp_cursor()

    @property
    def selectable_rows(self) -> tuple[Mapping[str, Any], ...]:
        """Return the rows the cursor can land on right now."""
        listed = visible_rows(self._all_rows, show_hidden=self._show_hidden)
        return filter_rows(listed, self._query)

    @property
    def cursor_row(self) -> Mapping[str, Any] | None:
        """Return the highlighted row, if any."""
        rows = self.selectable_rows
        if not rows:
            return None
        return rows[max(0, min(self._cursor, len(rows) - 1))]

    @property
    def is_filtering(self) -> bool:
        """Return whether keystrokes are editing the filter draft."""
        return self._filtering

    def _clamp_cursor(self) -> None:
        total = len(self.selectable_rows)
        if total <= 0:
            self._cursor = 0
            return
        self._cursor = max(0, min(self._cursor, total - 1))

    def _is_current_row(self, row: Mapping[str, Any]) -> bool:
        try:
            ordinal = int(row.get("ordinal", -1))
        except (TypeError, ValueError):
            return False
        if ordinal != self._current_ordinal:
            return False
        if ordinal == 0:
            return str(row.get("class", "")) == self._current_class
        return True

    def compose(self) -> ComposeResult:
        with Container(id="pager-timeline"):
            yield Static(id="pager-timeline-header")
            yield Static(id="pager-timeline-list")
            yield Static(id="pager-timeline-footer")

    def on_mount(self) -> None:
        self._render_picker()

    def _list_width(self) -> int:
        """Return the usable cells for one picker row."""
        try:
            size = self.query_one("#pager-timeline-list", Static).size
            if int(size.width) >= 20:
                return max(int(size.width) - 4, 20)
        except Exception:
            pass
        try:
            app_width = int(self.app.size.width)
        except Exception:
            return 80
        # Mirror the modal CSS: width 88 capped at 94%, minus the
        # border and the list padding.
        return max(min(88, int(app_width * 0.94)) - 6, 20)

    def _footer_preview(self) -> str:
        """Return the live footer previewing the cursor row's actions."""
        try:
            from sase.memory.history.timeline_picker import picker_footer_preview
        except Exception:
            return _PICKER_FOOTER
        try:
            # The footer has one cell of padding per side where the
            # list has two, so it fits two more cells than one row.
            return picker_footer_preview(
                self.cursor_row,
                open_ordinal=self._current_ordinal,
                open_class=self._current_class,
                width=self._list_width() + 2,
            )
        except Exception:
            return _PICKER_FOOTER

    def _render_picker(self) -> None:
        rows = self.selectable_rows
        if self._filtering:
            header = Text(f"{self._base_title} — / {self._draft}▌")
        elif self._query:
            header = Text(f"{self._base_title} — / {self._query}")
        else:
            header = Text(f"{self._base_title} — / filter")
        self.query_one("#pager-timeline-header", Static).update(header)
        body = Text(no_wrap=True, overflow="crop")
        if not rows:
            body.append("(no matches — esc clears the filter)\n", style="dim")
        else:
            columns = _picker_columns(rows, self._list_width())
            start, end = picker_window(len(rows), self._cursor, _PICKER_WINDOW_HEIGHT)
            for index in range(start, end):
                row = rows[index]
                is_open = self._is_current_row(row)
                is_cursor = index == self._cursor
                line = _format_picker_row(
                    row,
                    columns,
                    is_open=is_open,
                    is_cursor=is_cursor,
                    open_style=self._open_style,
                )
                if is_cursor:
                    line.stylize(_CURSOR_STYLE)
                body.append_text(line)
                body.append("\n")
        if self._hidden_summary and not self._show_hidden:
            body.append(f"{self._hidden_summary}\n", style="dim")
        self.query_one("#pager-timeline-list", Static).update(body)
        self.query_one("#pager-timeline-footer", Static).update(
            Text(self._footer_preview(), style="dim")
        )

    def _move_cursor(self, delta: int) -> None:
        if not self.selectable_rows:
            return
        self._cursor = max(0, min(self._cursor + delta, len(self.selectable_rows) - 1))
        self._render_picker()

    def action_picker_down(self) -> None:
        if self._filtering:
            return
        self._move_cursor(1)

    def action_picker_up(self) -> None:
        if self._filtering:
            return
        self._move_cursor(-1)

    def action_picker_top(self) -> None:
        if self._filtering:
            return
        if self.selectable_rows:
            self._cursor = 0
            self._render_picker()

    def action_picker_bottom(self) -> None:
        if self._filtering:
            return
        if self.selectable_rows:
            self._cursor = len(self.selectable_rows) - 1
            self._render_picker()

    def action_picker_open(self) -> None:
        if self._filtering:
            self._commit_filter()
            return
        row = self.cursor_row
        if row is None:
            self.notify("No matches.", severity="information")
            return
        self.dismiss(
            {
                "action": "open",
                "ordinal": row.get("ordinal", 0),
                "class": row.get("class", ""),
            }
        )

    def action_picker_compare(self) -> None:
        if self._filtering:
            return
        row = self.cursor_row
        if row is None:
            self.notify("No matches.", severity="information")
            return
        self.dismiss(
            {
                "action": "compare",
                "ordinal": row.get("ordinal", 0),
                "class": row.get("class", ""),
            }
        )

    def action_picker_hidden(self) -> None:
        if self._filtering:
            return
        self._show_hidden = not self._show_hidden
        self._clamp_cursor()
        self._render_picker()

    def action_picker_filter(self) -> None:
        if not self._filtering:
            self._filtering = True
            self._draft = self._query
            self._render_picker()

    def action_picker_escape(self) -> None:
        if self._filtering:
            self._filtering = False
            self._draft = ""
            self._render_picker()
            return
        if self._query:
            self._query = ""
            self._cursor = 0
            self._render_picker()
            return
        self.dismiss(None)

    def _commit_filter(self) -> None:
        self._filtering = False
        self._query = self._draft
        self._cursor = 0
        self._clamp_cursor()
        self._render_picker()

    def on_key(self, event: Key) -> None:
        """Capture filter keystrokes while ``/`` editing is active."""
        if not self._filtering:
            return
        key = event.key
        if key == "backspace":
            self._draft = self._draft[:-1]
            self._render_picker()
            event.prevent_default()
            event.stop()
            return
        character = event.character
        if character is None and key == "space":
            character = " "
        if character is not None and len(character) == 1 and character.isprintable():
            self._draft += character
            self._render_picker()
            event.prevent_default()
            event.stop()


__all__ = [
    "TimelinePickerScreen",
]

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

from typing import Any
from collections.abc import Mapping

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

#: Style for the cursor line and for the open version's row.
_CURSOR_STYLE = "reverse"
_CURRENT_STYLE = "#9d7cd8"

_PICKER_FOOTER = (
    "⏎ open · = compare with open version · . hidden · / filter · esc close"
)


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
            start, end = picker_window(len(rows), self._cursor, _PICKER_WINDOW_HEIGHT)
            for index in range(start, end):
                row = rows[index]
                line = str(row.get("display", ""))
                if index == self._cursor:
                    body.append(f"▸ {line}\n", style=_CURSOR_STYLE)
                elif self._is_current_row(row):
                    body.append(f"  {line}\n", style=_CURRENT_STYLE)
                else:
                    body.append(f"  {line}\n")
        if self._hidden_summary and not self._show_hidden:
            body.append(f"{self._hidden_summary}\n", style="dim")
        self.query_one("#pager-timeline-list", Static).update(body)
        self.query_one("#pager-timeline-footer", Static).update(
            Text(_PICKER_FOOTER, style="dim")
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


__all__ = ["TimelinePickerScreen"]

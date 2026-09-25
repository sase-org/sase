"""Floating-popup layout for ``CommandLineScreen``.

The popup card and the doc-peek beside it live in one float on the frame's
overlay layer, docked above the input row, so opening and closing them never
reflows the transcript. Layout is synchronous and in memory (tui_perf rule
1): it reads widget geometry and assigns styles, nothing more.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from sase.ace.tui.command_line.chrome import CommandLineFrame
from sase.ace.tui.command_line.input import CommandLineInput
from sase.ace.tui.command_line.popup import CommandLinePopup
from sase.ace.tui.command_line.popup_layout import (
    POPUP_BOTTOM_RESERVE,
    popup_content_width,
    popup_geometry,
)

#: Border (2) plus horizontal padding (2) around the doc-peek text.
_PEEK_CHROME = 4

#: Rows the doc-peek may occupy (its CSS ``max-height``).
_PEEK_MAX_ROWS = 12

#: Rows of chrome around the popup list: the card border (2).
_CARD_BORDER_ROWS = 2

#: Fewest rows a clamped popup card may keep (border plus one line).
_MIN_CARD_ROWS = 3


class CommandLineScreenPopupLayoutMixin:
    """Behavior mixed into the public command-line screen."""

    _doc_peek_text: str

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _anchor_column(self, widget: CommandLineInput, frame: CommandLineFrame) -> int:
        """Return the replace-span column, relative to the frame's content."""
        line = widget.text
        start = min(max(self._popup_state.replace_start, 0), len(line))
        origin = widget.content_region.x + widget.gutter_width - widget.scroll_offset.x
        return origin + cell_len(line[:start]) - frame.content_region.x

    def _layout_popup(self) -> None:
        """Place the floating popup above the input at the replace column.

        Idempotent and cheap: callers repaint the popup, footer, or doc-peek
        and then call this to resize and reposition the float.
        """
        try:
            frame = self.query_one("#command-line-frame", CommandLineFrame)
            float_ = self.query_one("#command-line-popup-float", Horizontal)
            card = self.query_one("#command-line-popup-card", Vertical)
            popup = self.query_one(CommandLinePopup)
            footer = self.query_one("#command-line-popup-footer", Static)
            peek = self.query_one("#command-line-doc-peek", Static)
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen has no popup.
            return
        peek_shown = peek.display and popup.display
        if not (popup.display or footer.display):
            float_.display = False
            return
        float_.display = True
        available = frame.content_region.width
        room = max(frame.content_region.height - POPUP_BOTTOM_RESERVE, _MIN_CARD_ROWS)
        rows = popup.option_count if popup.display else 0
        card_rows = rows + (1 if footer.display else 0) + _CARD_BORDER_ROWS
        peek_natural = 0
        if peek_shown:
            widest = max(
                (cell_len(line) for line in self._doc_peek_text.splitlines()),
                default=0,
            )
            peek_natural = widest + _PEEK_CHROME
        try:
            anchor = self._anchor_column(widget, frame)
        except Exception:  # noqa: BLE001 - geometry reads are best effort.
            anchor = 0
        geometry = popup_geometry(
            anchor=anchor,
            content=popup_content_width(popup.items) if popup.display else 0,
            peek=peek_natural,
            available=available,
        )
        float_.styles.margin = (0, 0, POPUP_BOTTOM_RESERVE, 0)
        float_.styles.offset = (geometry.x, 0)
        card.styles.width = geometry.card_width
        card.styles.height = min(card_rows, room)
        peek.display = peek_shown and geometry.peek_width > 0
        if geometry.peek_width:
            peek.styles.width = geometry.peek_width
            peek.styles.max_height = min(_PEEK_MAX_ROWS, room)

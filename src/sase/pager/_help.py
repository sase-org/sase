"""The `?` full binding sheet: cheat-sheet content plus its modal screen.

The footer legend only names the verbs worth a permanent row (see
``_chrome.footer_legend``); every binding lives here instead, per the design
doc's beauty rule that ``?`` is the cheat sheet, not a second footer.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

_BINDING_ROWS: tuple[tuple[str, str], ...] = (
    ("q, escape", "Close the pager"),
    ("j / k, down / up", "Scroll one line"),
    ("ctrl+d / ctrl+u", "Scroll half a page"),
    ("g / G", "Jump to top / bottom"),
    ("r", "Refresh"),
    ("/", "Search forward"),
    ("n / N", "Next / previous match"),
    ("?", "Show this help"),
)

_SECTION_BINDING_ROWS: tuple[tuple[str, str], ...] = (
    ("ctrl+n / ctrl+p", "Next / previous section"),
)


def _pager_help_text(*, section_total: int) -> Text:
    """Build the full key-binding sheet, pure and Textual-free."""
    rows = list(_BINDING_ROWS)
    if section_total > 1:
        rows[5:5] = _SECTION_BINDING_ROWS
    width = max(len(key) for key, _label in rows)

    text = Text()
    text.append("SasePager keys\n\n", style="bold")
    for index, (key, label) in enumerate(rows):
        if index > 0:
            text.append("\n")
        text.append(key.rjust(width), style="bold")
        text.append("  ")
        text.append(label)
    return text


class PagerHelpScreen(ModalScreen[None]):
    """The full binding-sheet modal, dismissed by the same keys as close."""

    BINDINGS = [Binding("q,escape,question_mark", "dismiss_help", "Close")]

    def __init__(self, *, section_total: int) -> None:
        super().__init__()
        self._section_total = section_total

    def compose(self) -> ComposeResult:
        with Container(id="pager-help"):
            yield Static(_pager_help_text(section_total=self._section_total))

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


__all__ = ["PagerHelpScreen", "_pager_help_text"]

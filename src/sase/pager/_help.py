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

_LINK_BINDING_ROWS: tuple[tuple[str, str], ...] = (
    ("0-9 / a-z / A-Z", "Follow a painted link"),
    ("y…, yy", "Copy a link's ref or path / this section"),
    ("E…, EE", "Edit a link in $EDITOR / this section"),
)
_SECTION_BINDING_ROWS: tuple[tuple[str, str], ...] = (
    ("ctrl+n / ctrl+p", "Next / previous section"),
)


def _pager_help_text(*, section_total: int, label_count: int = 0) -> Text:
    """Build the full key-binding sheet, pure and Textual-free."""
    rows = list(_BINDING_ROWS)
    if label_count:
        rows[5:5] = _LINK_BINDING_ROWS
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

    def __init__(self, *, section_total: int, label_count: int = 0) -> None:
        super().__init__()
        self._section_total = section_total
        self._label_count = label_count

    def compose(self) -> ComposeResult:
        with Container(id="pager-help"):
            yield Static(
                _pager_help_text(
                    section_total=self._section_total,
                    label_count=self._label_count,
                )
            )

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


__all__ = ["PagerHelpScreen", "_pager_help_text"]

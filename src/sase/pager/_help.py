"""The `?` full binding sheet: cheat-sheet content plus its modal screen.

The footer legend only names the verbs worth a permanent row (see
``_chrome.footer_legend``); every binding lives here instead, per the design
doc's beauty rule that ``?`` is the cheat sheet, not a second footer.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.modals.trail_strip import TrailStripEntry, append_trail_entry

_BINDING_ROWS: tuple[tuple[str, str], ...] = (
    ("q, escape", "Close the pager"),
    ("j / k, down / up", "Scroll one line"),
    ("ctrl+d / ctrl+u", "Scroll half a page"),
    ("g / G", "Jump to top / bottom"),
    ("backspace / ctrl+o", "Walk back"),
    ("ctrl+i", "Walk forward"),
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


def _pager_help_text(
    *,
    section_total: int,
    label_count: int = 0,
    trail_entries: Sequence[TrailStripEntry] = (),
) -> Text:
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
    if trail_entries:
        text.append("\n\nTrail\n", style="bold")
        for index, entry in enumerate(trail_entries, start=1):
            text.append("\n")
            text.append(f"{index:>2}. ", style="dim")
            append_trail_entry(text, entry)
    return text


class PagerHelpScreen(ModalScreen[None]):
    """The full binding-sheet modal, dismissed by the same keys as close."""

    BINDINGS = [Binding("q,escape,question_mark", "dismiss_help", "Close")]

    def __init__(
        self,
        *,
        section_total: int,
        label_count: int = 0,
        trail_entries: Sequence[TrailStripEntry] = (),
    ) -> None:
        super().__init__()
        self._section_total = section_total
        self._label_count = label_count
        self._trail_entries = tuple(trail_entries)

    def compose(self) -> ComposeResult:
        with Container(id="pager-help"):
            yield Static(
                _pager_help_text(
                    section_total=self._section_total,
                    label_count=self._label_count,
                    trail_entries=self._trail_entries,
                )
            )

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


__all__ = ["PagerHelpScreen", "_pager_help_text"]

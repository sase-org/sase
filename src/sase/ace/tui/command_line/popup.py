"""Floating fuzzy completion popup for the ``:`` Command Line panel.

The popup floats over the transcript, anchored just above the input (as in
Helix), and shows at most :data:`POPUP_MAX_VISIBLE_ROWS` rows. Ranking is
the Rust ``complete()`` response; this module owns the row rendering and
the zsh menu-select key state machine:

- ``Tab`` inserts the unique candidate or the longest common prefix.
  Otherwise it activates the menu, and later presses cycle through it.
- ``Enter`` accepts the highlighted item while the menu is active, and
  runs the line otherwise.
- ``Escape`` leaves the menu and restores the typed text; with no menu
  the event propagates to the panel rules (NORMAL mode or hide).
- ``ctrl+n`` / ``ctrl+p`` activate the menu and move within it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets._option_list import Option

#: Maximum visible popup rows; the list scrolls past this.
POPUP_MAX_VISIBLE_ROWS = 8

PopupAction = Literal[
    "accept",
    "complete-prefix",
    "activate",
    "move",
    "leave-menu",
    "propagate",
    "submit",
    "none",
]

__all__ = [
    "POPUP_MAX_VISIBLE_ROWS",
    "CommandLinePopup",
    "PopupAction",
    "PopupDecision",
    "CompletionPopupState",
    "popup_footer",
]


@dataclass(frozen=True, slots=True)
class PopupDecision:
    """One state-machine outcome for a popup key."""

    action: PopupAction
    #: Text to accept or insert (for ``accept`` / ``complete-prefix``).
    text: str | None = None


def _longest_common_prefix(values: list[str]) -> str:
    """Return the longest common prefix shared by all *values*."""
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        length = min(len(prefix), len(value))
        index = 0
        while index < length and prefix[index] == value[index]:
            index += 1
        prefix = prefix[:index]
        if not prefix:
            return ""
    return prefix


@dataclass
class CompletionPopupState:
    """The zsh menu-select state machine (Textual-free, fully testable)."""

    items: list[dict[str, Any]] = field(default_factory=list)
    menu_active: bool = False
    index: int = 0
    typed_text: str = ""
    replace_start: int = 0
    replace_end: int = 0

    @property
    def has_items(self) -> bool:
        """Return True when the popup has anything to offer."""
        return bool(self.items)

    @property
    def highlighted(self) -> dict[str, Any] | None:
        """Return the highlighted item while the menu is active."""
        if not self.menu_active or not self.items:
            return None
        return self.items[self.index % len(self.items)]

    def reset(
        self,
        items: list[dict[str, Any]],
        *,
        typed_text: str,
        replace_start: int,
        replace_end: int,
    ) -> None:
        """Replace the item list for a new keystroke; the menu goes idle."""
        self.items = list(items)
        self.menu_active = False
        self.index = 0
        self.typed_text = typed_text
        self.replace_start = replace_start
        self.replace_end = replace_end

    def on_tab(self) -> PopupDecision:
        """Apply the Tab rule: unique/LCP insert, else activate, else cycle."""
        if not self.items:
            return PopupDecision("none")
        if not self.menu_active:
            if len(self.items) == 1:
                return PopupDecision(
                    "accept", text=str(self.items[0].get("insert_text", ""))
                )
            prefix = _longest_common_prefix(
                [str(item.get("insert_text", "")) for item in self.items]
            )
            typed = self.typed_text[self.replace_start : self.replace_end]
            if len(prefix) > len(typed):
                return PopupDecision("complete-prefix", text=prefix)
            self.menu_active = True
            self.index = 0
            return PopupDecision("activate")
        self.index = (self.index + 1) % len(self.items)
        return PopupDecision("move")

    def on_shift_tab(self) -> PopupDecision:
        """Apply the Shift-Tab rule: activate, else cycle backward."""
        if not self.items:
            return PopupDecision("none")
        if not self.menu_active:
            self.menu_active = True
            self.index = 0
            return PopupDecision("activate")
        self.index = (self.index - 1) % len(self.items)
        return PopupDecision("move")

    def on_enter(self) -> PopupDecision:
        """Accept the highlight while active; otherwise run the line."""
        highlighted = self.highlighted
        if highlighted is None:
            return PopupDecision("submit")
        return PopupDecision("accept", text=str(highlighted.get("insert_text", "")))

    def on_escape(self) -> PopupDecision:
        """Leave the menu (restoring typed text) or propagate to the panel."""
        if not self.menu_active:
            return PopupDecision("propagate")
        self.menu_active = False
        self.index = 0
        return PopupDecision("leave-menu", text=self.typed_text)

    def on_ctrl_n(self) -> PopupDecision:
        """Activate the menu and move down."""
        if not self.items:
            return PopupDecision("none")
        if not self.menu_active:
            self.menu_active = True
            self.index = 0
            return PopupDecision("activate")
        self.index = (self.index + 1) % len(self.items)
        return PopupDecision("move")

    def on_ctrl_p(self) -> PopupDecision:
        """Activate the menu and move up."""
        if not self.items:
            return PopupDecision("none")
        if not self.menu_active:
            self.menu_active = True
            self.index = len(self.items) - 1
            return PopupDecision("activate")
        self.index = (self.index - 1) % len(self.items)
        return PopupDecision("move")


_GLYPHS = {
    "agent": "◆",
    "proc": "⠹",
    "project": "⌂",
    "patch": "▤",
}


def _render_popup_row(item: dict[str, Any]) -> Text:
    """Render one ranked completion item as a popup row.

    Rows follow the visual-language spec: entity glyph, value (fuzzy
    match runs highlighted), kind badge, and description columns.
    Selected-entity rows are marked ``◆ … sel``.
    """
    source = str(item.get("source", "") or "")
    glyph = _GLYPHS.get(source, "·")
    display = str(item.get("display", "") or item.get("insert_text", ""))
    text = Text()
    if item.get("selected"):
        text.append("◆ ", style="bold #00D7AF")
    else:
        text.append(f"{glyph} ", style="dim")
    runs = item.get("match_runs") or []
    if runs and display:
        cursor = 0
        for run in runs:
            try:
                start, end = int(run[0]), int(run[1])
            except (IndexError, TypeError, ValueError):
                continue
            start = max(0, min(start, len(display)))
            end = max(start, min(end, len(display)))
            if start > cursor:
                text.append(display[cursor:start])
            text.append(display[start:end], style="bold")
            cursor = end
        if cursor < len(display):
            text.append(display[cursor:])
    else:
        text.append(display)
    badge = str(item.get("badge", "") or "")
    if badge:
        text.append(f"  [{badge}]", style="dim #87D7FF")
    description = str(item.get("description", "") or "")
    if description:
        text.append(f"  {description}", style="dim")
    if item.get("selected"):
        text.append("  sel", style="bold #00D7AF")
    return text


def popup_footer(kind: str, shown: int, total: int) -> str:
    """Render the popup footer: ``<kind> · N of M · fuzzy`` plus key hint."""
    return f"{kind} · {shown} of {total} · fuzzy    ⇥ accept"


class CommandLinePopup(OptionList):
    """The floating completion list, anchored just above the input."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", "command-line-popup")
        super().__init__(**kwargs)
        self._applying_programmatic_highlight = False

    def show_items(self, items: list[dict[str, Any]]) -> None:
        """Replace the visible rows (at most 8) without echoing highlights."""
        self._applying_programmatic_highlight = True
        try:
            self.clear_options()
            for item in items[:POPUP_MAX_VISIBLE_ROWS]:
                self.add_option(Option(_render_popup_row(item)))
        finally:
            self._applying_programmatic_highlight = False
        self.display = bool(items)

    def highlight_index(self, index: int) -> None:
        """Move the highlight without tripping the echo guard."""
        if not self._options:
            return
        self._applying_programmatic_highlight = True
        try:
            self.highlighted = index % len(self._options)
        finally:
            self._applying_programmatic_highlight = False

    @property
    def echo_guarded(self) -> bool:
        """Return True while a highlight change is programmatic (rule 12)."""
        return self._applying_programmatic_highlight

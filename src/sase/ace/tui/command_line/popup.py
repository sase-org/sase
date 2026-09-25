"""Floating fuzzy completion popup for the ``:`` Command Line panel.

The popup floats over the transcript, anchored just above the input (as in
Helix), and shows a scrolling window of at most
:data:`POPUP_MAX_VISIBLE_ROWS` candidates (plus the section headings among
them) over every candidate. Ranking is the
Rust ``complete()`` response; this module owns the row rendering, the
window, and the zsh menu-select key state machine:

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

#: Maximum candidate rows in the popup window; the window scrolls past this.
#: Section headings are extra, non-selectable rows on top of it.
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


def popup_footer(
    kind: str,
    position: int,
    total: int,
    *,
    menu_active: bool = False,
    note: str | None = None,
) -> str:
    """Render the popup footer: ``<kind> · N of M · fuzzy`` plus one key hint.

    *position* is the highlighted row's 1-based index while the menu is
    active and the loaded row count otherwise. The key hint follows the menu
    state: Tab completes from the idle popup, Enter accepts inside the menu.
    """
    hint = "⏎ accept" if menu_active else "⇥ complete"
    text = f"{kind} · {position} of {total} · fuzzy    {hint}"
    if note:
        text += f"  {note}"
    return text


@dataclass(frozen=True, slots=True)
class _PopupEntry:
    """One popup display row: a section heading or a completion item."""

    #: Index into the popup's items; ``None`` marks a heading row.
    item_index: int | None
    #: Heading text (only for heading rows).
    heading: str = ""


def _build_entries(items: list[dict[str, Any]]) -> list[_PopupEntry]:
    """Interleave non-selectable section headings between *items*.

    A row carries its section in ``item["section"]``; a heading precedes the
    first row of each new section (the empty-state ``RECENT`` and
    ``FOR <selection>`` groups).
    """
    entries: list[_PopupEntry] = []
    section = ""
    for index, item in enumerate(items):
        row_section = str(item.get("section", "") or "")
        if row_section != section:
            section = row_section
            if section:
                entries.append(_PopupEntry(None, section))
        entries.append(_PopupEntry(index))
    return entries


class CommandLinePopup(OptionList):
    """The floating completion list, anchored just above the input.

    The widget renders only the window of :data:`POPUP_MAX_VISIBLE_ROWS`
    display rows around the highlight, so per-keystroke cost stays bounded
    while every candidate stays reachable: :meth:`highlight_index` scrolls
    the window to keep the state machine's item index visible. Section
    headings are disabled rows that never take the highlight and do not
    count against the window's row budget.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", "command-line-popup")
        super().__init__(**kwargs)
        self._items: list[dict[str, Any]] = []
        self._entries: list[_PopupEntry] = []
        self._entry_for_item: list[int] = []
        #: First item of the window, and the entry position its slice starts at.
        self._window_first = 0
        self._window_pos = 0
        #: Rule 12: programmatic highlights echo later as queued messages, so
        #: count the echoes still in flight per window row instead of
        #: toggling a flag that is long cleared by the time they arrive.
        self._pending_echoes: dict[int, int] = {}

    def show_items(self, items: list[dict[str, Any]]) -> None:
        """Replace every candidate; the window resets to the top."""
        self._items = list(items)
        self._entries = _build_entries(self._items)
        self._entry_for_item = [0] * len(self._items)
        for position, entry in enumerate(self._entries):
            if entry.item_index is not None:
                self._entry_for_item[entry.item_index] = position
        self._window_first = 0
        self._rebuild_window()
        self.display = bool(items)

    def highlight_index(self, index: int) -> None:
        """Highlight item *index*, scrolling the window to keep it visible."""
        if not self._items:
            return
        target = index % len(self._items)
        first = self._window_first
        if target < first:
            first = target
        elif target >= first + POPUP_MAX_VISIBLE_ROWS:
            first = target - POPUP_MAX_VISIBLE_ROWS + 1
        if first != self._window_first:
            self._window_first = first
            self._rebuild_window()
        self._set_highlight(self._entry_for_item[target] - self._window_pos)

    def clear_highlight(self) -> None:
        """Drop the highlight and scroll the window back to the top."""
        if self._window_first:
            self._window_first = 0
            self._rebuild_window()
        self.highlighted = None

    def user_highlight_index(self, event: OptionList.OptionHighlighted) -> int | None:
        """Return the item index for a user-driven highlight *event*.

        Programmatic echoes, stale messages from a replaced row list, and
        heading rows all return ``None`` so they never reset the state
        machine's index.
        """
        row = event.option_index
        if row >= len(self._options) or self._options[row] is not event.option:
            return None  # A replaced list: the option is no longer ours.
        pending = self._pending_echoes.get(row, 0)
        if pending:
            if pending == 1:
                del self._pending_echoes[row]
            else:
                self._pending_echoes[row] = pending - 1
            return None
        position = self._window_pos + row
        if position >= len(self._entries):
            return None
        return self._entries[position].item_index

    def _set_highlight(self, row: int) -> None:
        """Assign the highlight and record the echo it will post."""
        if self.highlighted != row:
            self._pending_echoes[row] = self._pending_echoes.get(row, 0) + 1
        self.highlighted = row

    def _rebuild_window(self) -> None:
        """Render the window's rows (and the headings among them) as options."""
        self._pending_echoes.clear()
        options: list[Option] = []
        self._window_pos = 0
        if self._items:
            last = (
                min(self._window_first + POPUP_MAX_VISIBLE_ROWS, len(self._items)) - 1
            )
            start = self._entry_for_item[self._window_first]
            if start > 0 and self._entries[start - 1].item_index is None:
                start -= 1  # The first row opens its section: keep the heading.
            self._window_pos = start
            for entry in self._entries[start : self._entry_for_item[last] + 1]:
                if entry.item_index is None:
                    options.append(
                        Option(Text(entry.heading, style="bold dim"), disabled=True)
                    )
                else:
                    options.append(
                        Option(_render_popup_row(self._items[entry.item_index]))
                    )
        self.clear_options()
        self.add_options(options)

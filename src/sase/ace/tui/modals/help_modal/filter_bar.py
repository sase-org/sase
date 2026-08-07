"""Filter input and status/empty-state rendering for the Help panel filter bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Input

from .filter_model import FilterResult

if TYPE_CHECKING:
    from .modal import HelpModal


class HelpFilterInput(Input):
    """Filter input that scrolls results and hands escape to the Help modal."""

    BINDINGS = [
        Binding("up", "scroll_results_up", "Scroll up", show=False),
        Binding("down", "scroll_results_down", "Scroll down", show=False),
        Binding("pageup", "scroll_results_page_up", "Page up", show=False),
        Binding("pagedown", "scroll_results_page_down", "Page down", show=False),
    ]

    def on_key(self, event: events.Key) -> None:
        if event.key != "escape":
            return
        modal = self._modal()
        if modal is None:
            return
        event.stop()
        event.prevent_default()
        modal.action_close()

    def action_scroll_results_up(self) -> None:
        self._scroll(-1)

    def action_scroll_results_down(self) -> None:
        self._scroll(1)

    def action_scroll_results_page_up(self) -> None:
        self._scroll(-2)

    def action_scroll_results_page_down(self) -> None:
        self._scroll(2)

    def _scroll(self, half_pages: int) -> None:
        modal = self._modal()
        if modal is None:
            return
        try:
            scroll = modal.query_one("#help-keymaps-scroll", VerticalScroll)
        except (NoMatches, LookupError):
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=(height // 2) * half_pages, animate=False)

    def _modal(self) -> HelpModal | None:
        from .modal import HelpModal

        screen = self.screen
        return screen if isinstance(screen, HelpModal) else None


def build_filter_status(result: FilterResult) -> Text:
    """Build the keymap/section counter chip for the filter bar."""
    if not result.active:
        return Text("")
    if result.keymap_count == 0:
        return Text("no matches", style="dim italic")
    text = Text()
    text.append(
        f"{result.keymap_count} keymaps · {result.section_count} sections",
        style="dim",
    )
    if result.relaxed:
        text.append(" · ~ fuzzy", style="dim italic")
    return text


def build_filter_empty_state(query: str) -> Text:
    """Build the centered empty-state message shown when nothing matches."""
    text = Text()
    text.append(f'No keymaps match "{query}"', style="dim")
    text.append("\n")
    text.append("Esc clears the filter", style="dim italic")
    return text


__all__ = [
    "HelpFilterInput",
    "build_filter_empty_state",
    "build_filter_status",
]

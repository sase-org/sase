"""Contextual help for the Memory panel."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.keymaps import MemoryPanelKeymaps, memory_help_bindings

_ACCENT = "#87D7FF"


class MemoryPanelHelpModal(ModalScreen[None]):
    """List the Memory panel's effective keys."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "scroll_line_down", "Down"),
        ("k", "scroll_line_up", "Up"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, *, keymaps: MemoryPanelKeymaps) -> None:
        super().__init__()
        self._keymaps = keymaps
        self._bindings = BindingsMap(
            [
                Binding(
                    self._keymaps.help,
                    "close",
                    "Close",
                    show=False,
                    priority=True,
                ),
                *self.BINDINGS,
            ]
        )

    def compose(self) -> ComposeResult:
        with Container(id="memory-panel-help-container"):
            yield Static(self._title(), id="memory-panel-help-title")
            with VerticalScroll(id="memory-panel-help-scroll"):
                yield Static(self._content(), id="memory-panel-help-content")
            yield Static(
                f"j/k scroll  ·  {self._keymaps.help}/q/Esc close",
                id="memory-panel-help-footer",
            )

    def _title(self) -> Text:
        title = Text(justify="center")
        title.append("Memory Panel Help", style=f"bold {_ACCENT}")
        return title

    def _content(self) -> RenderableType:
        text = Text()
        for index, (key, description) in enumerate(memory_help_bindings(self._keymaps)):
            if index:
                text.append("\n")
            text.append(f" {key} ", style=f"bold reverse {_ACCENT}")
            text.append(f" {description}", style="bold")
        note = Text()
        note.append(
            "\nfollow_link ships as enter,l, but only l currently follows a chip: "
            "the note list holds focus and consumes Enter for its own selection "
            "action, so Enter does nothing in this panel. Use l or a chip number.",
            style="dim",
        )
        return Group(text, note)

    def _scroll(self) -> VerticalScroll:
        return self.query_one("#memory-panel-help-scroll", VerticalScroll)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_line_down(self) -> None:
        self._scroll().scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        self._scroll().scroll_relative(y=-1, animate=False)

    def action_scroll_down(self) -> None:
        scroll = self._scroll()
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2),
            animate=False,
        )

    def action_scroll_up(self) -> None:
        scroll = self._scroll()
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2),
            animate=False,
        )


__all__ = ["MemoryPanelHelpModal"]

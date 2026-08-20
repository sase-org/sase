"""Contextual help for the Snippets panel."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.keymaps import SnippetPanelKeymaps, snippet_help_bindings

_ACCENT = "#87D7FF"


class SnippetsPanelHelpModal(ModalScreen[None]):
    """List the Snippets panel's effective keys."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "scroll_line_down", "Down"),
        ("k", "scroll_line_up", "Up"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, *, keymaps: SnippetPanelKeymaps) -> None:
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
        with Container(id="snippets-panel-help-container"):
            yield Static(self._title(), id="snippets-panel-help-title")
            with VerticalScroll(id="snippets-panel-help-scroll"):
                yield Static(self._content(), id="snippets-panel-help-content")
            yield Static(
                f"j/k scroll  ·  {self._keymaps.help}/q/Esc close",
                id="snippets-panel-help-footer",
            )

    def _title(self) -> Text:
        title = Text(justify="center")
        title.append("Snippets Panel Help", style=f"bold {_ACCENT}")
        return title

    def _content(self) -> RenderableType:
        text = Text()
        for index, (key, description) in enumerate(
            snippet_help_bindings(self._keymaps)
        ):
            if index:
                text.append("\n")
            text.append(f" {key} ", style=f"bold reverse {_ACCENT}")
            text.append(f" {description}", style="bold")
        return Group(text)

    def _scroll(self) -> VerticalScroll:
        return self.query_one("#snippets-panel-help-scroll", VerticalScroll)

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


__all__ = ["SnippetsPanelHelpModal"]

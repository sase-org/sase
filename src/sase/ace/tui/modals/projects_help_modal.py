"""Contextual help for the Admin Center Projects pane."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingsMap
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.keymaps import (
    ProjectsPaneKeymaps,
    key_display_name,
    projects_help_bindings,
)

_ACCENT = "#FFAF5F"


class ProjectsHelpModal(ModalScreen[None]):
    """List the Projects pane's effective keys."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "scroll_line_down", "Down"),
        ("k", "scroll_line_up", "Up"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, *, keymaps: ProjectsPaneKeymaps) -> None:
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
        with Container(id="projects-help-container"):
            yield Static(self._title(), id="projects-help-title")
            with VerticalScroll(id="projects-help-scroll"):
                yield Static(self._content(), id="projects-help-content")
            yield Static(
                f"j/k scroll · {key_display_name(self._keymaps.help)}/q/Esc close",
                id="projects-help-footer",
            )

    def _title(self) -> Text:
        title = Text(justify="center")
        title.append("Projects Help", style=f"bold {_ACCENT}")
        return title

    def _content(self) -> RenderableType:
        text = Text()
        for index, (key, description) in enumerate(
            projects_help_bindings(self._keymaps)
        ):
            if index:
                text.append("\n")
            text.append(f" {key} ", style=f"bold reverse {_ACCENT}")
            text.append(f" {description}", style="bold")
        return text

    def _scroll(self) -> VerticalScroll:
        return self.query_one("#projects-help-scroll", VerticalScroll)

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


__all__ = ["ProjectsHelpModal"]

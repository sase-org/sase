"""Scrollable panel for definitions returned by the DICT client."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.core.word_lookup import DefinitionSection


class WordDefinitionModal(ModalScreen[None]):
    """Display one or more dictionary definitions for a prompt word."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
    ]

    def __init__(
        self,
        word: str,
        sections: tuple[DefinitionSection, ...],
    ) -> None:
        super().__init__()
        self._word = word
        self._sections = sections

    def compose(self) -> ComposeResult:
        with Container(id="word-definition-container"):
            yield Static(self._build_title(), id="word-definition-title")
            with VerticalScroll(id="word-definition-scroll"):
                yield Static(self._build_content(), id="word-definition-content")
            yield Static(
                "Ctrl+D/U scroll | j/k line | g/G top/bottom | Esc/q close",
                id="word-definition-footer",
            )

    def _build_title(self) -> Text:
        title = Text()
        title.append("≡", style="bold #FFD700")
        title.append(" ")
        title.append("WORD", style="bold #87D7FF")
        title.append("  ")
        title.append(self._word, style="bold white")
        title.append("\n")
        sources = ", ".join(section.source for section in self._sections)
        title.append(f"dict.org — {sources}", style="dim #87D7FF")
        return title

    def _build_content(self) -> Text:
        content = Text()
        for index, section in enumerate(self._sections):
            if index:
                content.append("\n\n")
            content.append(f"─── {section.source} ───", style="dim cyan")
            if section.body:
                content.append("\n")
                content.append(section.body)
        return content

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#word-definition-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


__all__ = ["WordDefinitionModal"]

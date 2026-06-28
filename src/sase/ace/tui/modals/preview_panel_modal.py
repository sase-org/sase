"""Scrollable syntax-highlighted preview modal."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache, lazy_renderable
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload


class PreviewPanelModal(ModalScreen[None]):
    """Presentational modal for resolved xprompt/file previews."""

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

    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self._payload = payload
        self._syntax_render_cache = LazySyntaxRenderCache()

    def compose(self) -> ComposeResult:
        with Container(id="preview-modal-container"):
            yield Static(self._build_title(), id="preview-title")
            with VerticalScroll(id="preview-scroll"):
                yield Static(self._build_content(), id="preview-content")
            yield Static(
                "Ctrl+D/U scroll | j/k line | g/G top/bottom | Esc/q close",
                id="preview-footer",
            )

    def _build_title(self) -> Text:
        text = Text()
        text.append(self._payload.icon, style="bold #FFD700")
        text.append(" ")
        text.append(self._payload.kind_label.upper(), style="bold #87D7FF")
        text.append("  ")
        text.append(self._payload.title, style="bold white")
        if self._payload.source_path:
            text.append("\n")
            text.append(self._payload.source_path, style="dim #87D7FF")
        return text

    def _build_content(self) -> RenderableType:
        return lazy_renderable(
            self._payload.content,
            self._payload.lexer,
            line_numbers=True,
            theme="monokai",
            render_cache=self._syntax_render_cache,
        )

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#preview-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


__all__ = ["PreviewPanelModal"]

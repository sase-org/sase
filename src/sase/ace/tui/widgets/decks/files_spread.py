"""Spread view for Files decks showing every page in order."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from ..file_panel._spread_probe import FilesSpreadPage
from ..prompt_panel._section_view import SectionViewMixin
from .separators import files_separator_for
from sase.ace.tui.util.lazy_syntax import (
    FILE_PANEL_MAX_RENDER_LINES,
    lazy_renderable,
)


class FilesSpreadView(SectionViewMixin, Static):
    """One Files spread view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Files spread view."""
        super().__init__(**kwargs)
        self._pages: tuple[FilesSpreadPage, ...] = ()
        self._last_render_key: tuple[object, ...] | None = None

    @property
    def page_slots(self) -> tuple[str, ...]:
        """Return the current spread page slots in order."""
        return tuple(page.slot for page in self._pages)

    def show_pages(
        self,
        pages: tuple[FilesSpreadPage, ...] | list[FilesSpreadPage],
        *,
        digest: str | None,
    ) -> None:
        """Show ``pages`` in order with titled separators."""
        pages_tuple = tuple(pages)
        render_key = (digest, tuple(p.slot for p in pages_tuple))
        if render_key == self._last_render_key and self._pages:
            return
        self.prepare_section_document((digest, "spread"))
        parts: list[Any] = []
        for index, page in enumerate(pages_tuple):
            if index > 0:
                parts.append(files_separator_for(f"file-{index}", page.label))
            header = Text(page.label, style="bold #D7AF5F underline")
            parts.append(header)
            parts.append(Text(""))
            body = lazy_renderable(
                page.text,
                page.lexer,
                line_numbers=True,
                max_render_lines=FILE_PANEL_MAX_RENDER_LINES,
            )
            parts.append(body)
        if not parts:
            self._apply_section_content(Text(""), digest, layout=True)
        else:
            spread_digest = None if digest is None else f"{digest}:spread"
            self._apply_section_content(Group(*parts), spread_digest, layout=True)
        self._pages = pages_tuple
        self._last_render_key = render_key

    def show_empty(self) -> None:
        """Clear the spread view."""
        self.prepare_section_document((None, "spread-empty"))
        self._apply_section_content(Text(""), None, layout=True)
        self._pages = ()
        self._last_render_key = None


__all__ = ["FilesSpreadView"]

"""``VimSearchController`` host protocol for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets.vim_search_controller import (
    SearchViewport,
    VimSearchMode,
)
from sase.pager._layout import search_corpus


class PagerSearchMixin:
    """Implement the search-controller host callbacks."""

    def vim_search_corpus(self: Any) -> str:
        return search_corpus(self.document)

    def vim_search_origin_scroll(self: Any) -> tuple[int, int]:
        scroll = self._body_scroll()
        return (int(scroll.scroll_x), int(scroll.scroll_y))

    def vim_search_overlay_viewport(self: Any) -> SearchViewport:
        scroll = self._body_scroll()
        region = scroll.scrollable_content_region
        return SearchViewport(
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            width=region.width,
            height=region.height,
        )

    def vim_search_started(self: Any) -> None:
        """No live refresh source to pause: the document is immutable."""

    def vim_search_exited(self: Any, *, refresh: bool) -> None:
        """The body is already restored by ``vim_search_hide_overlay``."""

    def vim_search_show_overlay(self: Any) -> None:
        self.query_one("#pager-search-command", Static).remove_class("hidden")

    def vim_search_hide_overlay(self: Any) -> None:
        if self._body is not None:
            self.query_one("#pager-body", Static).update(self._body.renderable)
        command = self.query_one("#pager-search-command", Static)
        command.update("")
        command.add_class("hidden")

    def vim_search_paint_overlay(self: Any, content: Text) -> None:
        self.query_one("#pager-body", Static).update(content)

    def vim_search_command_width(self: Any) -> int:
        command = self.query_one("#pager-search-command", Static)
        return max(0, int(command.size.width) - 2)

    def vim_search_paint_command_line(
        self: Any,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        command = self.query_one("#pager-search-command", Static)
        command.update(content)
        command.remove_class("hidden")

    def vim_search_scroll_overlay(self: Any, *, x: int, y: int) -> None:
        self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)

    def vim_search_restore_scroll(self: Any, *, x: int, y: int) -> None:
        def restore() -> None:
            self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
            self._update_subject()

        self.call_after_refresh(restore)

    def vim_search_focus_overlay(self: Any) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_focus_native(self: Any) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_notify(self: Any, message: str) -> None:
        self.notify(message, severity="information")


__all__ = ["PagerSearchMixin"]

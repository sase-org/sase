"""Small Textual widgets used by ``PagerScreen``."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from textual.containers import VerticalScroll
from textual.events import Resize
from textual.geometry import Size
from textual.widgets import Static


@runtime_checkable
class _PagerBodyHost(Protocol):
    _body_width: int | None
    _body: object | None

    def _ensure_body(self) -> None: ...

    def _after_scroll(self) -> None: ...

    def _update_chrome_position(self) -> None: ...


class PagerBodyScroll(VerticalScroll):
    """The body scroll container; its own width drives layout caching."""

    def on_resize(self, _event: Resize) -> None:
        screen = self.screen
        if isinstance(screen, _PagerBodyHost):
            screen._ensure_body()
            screen._update_chrome_position()

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_x(old_value, new_value)
        if old_value == new_value:
            return
        screen = self.screen
        if isinstance(screen, _PagerBodyHost):
            screen._after_scroll()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if old_value == new_value:
            return
        screen = self.screen
        if isinstance(screen, _PagerBodyHost):
            screen._after_scroll()


class PagerBody(Static):
    """Static body whose scroll height matches the pre-wrapped composed rows."""

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        del container, viewport, width
        screen = self.screen
        body = (
            getattr(screen, "_body", None)
            if isinstance(screen, _PagerBodyHost)
            else None
        )
        if body is not None:
            return max(int(body.total_height), 1)
        return 1


__all__ = ["PagerBody", "PagerBodyScroll"]

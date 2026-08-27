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

    def _ensure_body(self) -> None: ...

    def _update_subject(self) -> None: ...


class PagerBodyScroll(VerticalScroll):
    """The body scroll container; its own width drives layout caching."""

    def on_resize(self, _event: Resize) -> None:
        screen = self.screen
        if isinstance(screen, _PagerBodyHost):
            screen._ensure_body()
            screen._update_subject()


class PagerBody(Static):
    """Static body whose scroll height preserves standalone pager geometry."""

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        height = super().get_content_height(container, viewport, width)
        screen = self.screen
        if not isinstance(screen, _PagerBodyHost) or screen._body_width is None:
            return height
        composed_width_height = super().get_content_height(
            container, viewport, screen._body_width
        )
        if container.height < composed_width_height < height:
            return composed_width_height
        return height


__all__ = ["PagerBody", "PagerBodyScroll"]

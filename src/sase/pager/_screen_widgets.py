"""Small Textual widgets used by ``PagerView``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.events import Resize
from textual.geometry import Size
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from sase.pager.view import PagerView


def _owning_view(widget: Widget) -> PagerView | None:
    """Return the nearest ancestor ``PagerView``, if this widget has one."""
    from sase.pager.view import PagerView

    node = widget.parent
    while node is not None:
        if isinstance(node, PagerView):
            return node
        node = node.parent
    return None


class PagerBodyScroll(VerticalScroll):
    """The body scroll container; its own width drives layout caching."""

    def on_resize(self, _event: Resize) -> None:
        view = _owning_view(self)
        if view is not None:
            view._ensure_body()
            view._update_chrome_position()

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_x(old_value, new_value)
        if old_value == new_value:
            return
        view = _owning_view(self)
        if view is not None:
            view._after_scroll()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if old_value == new_value:
            return
        view = _owning_view(self)
        if view is not None:
            view._after_scroll()


class PagerBody(Static):
    """Static body whose scroll height matches the pre-wrapped composed rows."""

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        del container, viewport, width
        view = _owning_view(self)
        body = getattr(view, "_body", None) if view is not None else None
        if body is not None:
            return max(int(body.total_height), 1)
        return 1


__all__ = ["PagerBody", "PagerBodyScroll"]

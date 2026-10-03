"""Line-API body widget used by ``PagerView``."""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.cache import LRUCache
from textual.events import Resize
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widget import Widget

from sase.pager._body_lines import (
    SpanIndex,
    build_span_index,
    logical_line_end,
    logical_line_starts,
    slice_styled_line,
)

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


def _text_to_strip(console: Console, text: Text, width: int) -> Strip:
    """Render one row ``Text`` to a single strip at *width*.

    Uses the app console with wrapping disabled and cropping on, the same
    Line-API shape as ``textual.widgets.RichLog``.
    """
    source = text.copy()
    source.no_wrap = True
    source.overflow = "crop"
    options = console.options.update(overflow="crop", no_wrap=True).update_width(width)
    segments = console.render(source, options)
    strips = Strip.from_lines(list(Segment.split_lines(segments)))
    if strips:
        return strips[0]
    return Strip.blank(width)


def _plain_to_strip(plain: str, width: int, style: object) -> Strip:
    """Build a strip from uncropped *plain* text, cropped to *width*."""
    cropped = plain
    if cell_len(cropped) > width:
        kept: list[str] = []
        used = 0
        for character in cropped:
            advance = cell_len(character)
            if used + advance > width:
                break
            kept.append(character)
            used += advance
        cropped = "".join(kept)
    strip = Strip([Segment(cropped)]).crop_extend(0, width, style)  # type: ignore[arg-type]
    if style is not None:
        return strip.apply_style(style)  # type: ignore[arg-type]
    return strip


#: Side padding cells baked into every body strip, one per side. The old
#: inner-Static body carried ``padding: 0 1`` *inside* the scrollbar, so the
#: order was text, pad, scrollbar; widget-level padding would order it text,
#: scrollbar, pad and shift the scrollbar. Baking the pads into the strips
#: keeps every golden pixel-identical.
BODY_PAD_LEFT = 1
BODY_PAD_RIGHT = 1


class PagerBodyScroll(ScrollView):
    """The body scroll container; paints virtual rows through ``render_line``."""

    DEFAULT_CSS = """
    PagerBodyScroll {
        overflow-x: hidden;
        overflow-y: auto;
    }
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._strip_cache: LRUCache = LRUCache(maxsize=512)
        self._overlay_text: Text | None = None
        self._overlay_starts: array | None = None
        self._overlay_index: SpanIndex | None = None

    @property
    def overlay_active(self) -> bool:
        """Return whether the search overlay is the current paint source."""
        return self._overlay_text is not None

    @property
    def overlay_line_count(self) -> int:
        """Return the overlay's logical line count (0 without an overlay)."""
        starts = self._overlay_starts
        return len(starts) if starts is not None else 0

    def set_overlay(self, content: Text | None) -> None:
        """Show *content* as logical-line rows, or restore the model on None."""
        if content is None:
            self._overlay_text = None
            self._overlay_starts = None
            self._overlay_index = None
        else:
            base = content.copy()
            base.no_wrap = True
            base.overflow = "crop"
            self._overlay_text = base
            self._overlay_starts = logical_line_starts(base.plain)
            self._overlay_index = build_span_index(base)
        self.clear_strip_cache()
        self._refresh_virtual_size()
        self.refresh(layout=True)

    def overlay_line(self, row: int) -> Text:
        """Return overlay logical line *row* with its match styling."""
        base = self._overlay_text
        starts = self._overlay_starts
        index = self._overlay_index
        if base is None or starts is None or index is None or not starts:
            return Text("")
        clamped = max(0, min(row, len(starts) - 1))
        end = logical_line_end(starts, clamped, base.plain)
        return slice_styled_line(base, starts[clamped], end, index=index)

    def clear_strip_cache(self) -> None:
        """Drop every cached strip; the next paint re-renders visible rows."""
        self._strip_cache.clear()

    def on_unmount(self) -> None:
        self._strip_cache.clear()

    def render_line(self, y: int) -> Strip:
        """Paint absolute row ``scroll_y + y`` as one strip; never raises."""
        try:
            return self._render_line(y)
        except Exception:
            try:
                width = int(self.scrollable_content_region.width)
            except Exception:
                width = 1
            return Strip.blank(max(width, 1))

    def _active_height(self) -> int:
        """Return the painted row count of the active source."""
        if self._overlay_text is not None:
            return self.overlay_line_count
        view = _owning_view(self)
        body = getattr(view, "_body", None) if view is not None else None
        try:
            return int(body.total_height) if body is not None else 0
        except Exception:
            return 0

    def _strip_widths(self) -> tuple[int, int]:
        """Return the ``(outer, inner)`` strip widths in cells.

        The outer width is the full scrollable width (text plus the baked
        side pads); the inner width is what the line model wraps into.
        """
        try:
            outer = int(self.scrollable_content_region.width)
        except Exception:
            outer = 0
        if outer <= 0:
            try:
                outer = int(self.size.width)
            except Exception:
                outer = 1
        outer = max(outer, 1)
        inner = max(outer - BODY_PAD_LEFT - BODY_PAD_RIGHT, 1)
        return outer, inner

    def _render_line(self, y: int) -> Strip:
        offset = self.scroll_offset
        outer_width, render_width = self._strip_widths()
        view = _owning_view(self)
        try:
            viewport_height = max(int(self.size.height), 1)
        except Exception:
            viewport_height = 1
        self._strip_cache.grow(max(512, 4 * viewport_height))
        epoch = 0
        if view is not None:
            try:
                epoch = int(view._body_paint_epoch)
            except Exception:
                epoch = 0
        overlay = self._overlay_text is not None
        scroll_x = 0 if overlay else int(offset.x)
        absolute_row = int(offset.y) + y
        # Rows past the painted source stay blank: the line model clamps
        # out-of-range lookups to the last row by design, so the widget
        # must not ask for them (and must not count them as rendered).
        if not 0 <= absolute_row < self._active_height():
            blank = Strip.blank(outer_width)
            try:
                return blank.apply_style(self.rich_style)
            except Exception:
                return blank
        key = (absolute_row, epoch, outer_width, render_width, scroll_x)
        cached = self._strip_cache.get(key)
        if cached is not None:
            return cached
        try:
            style = self.rich_style
            try:
                pad_style: Style | None = Style(bgcolor=style.bgcolor)
            except Exception:
                pad_style = None
            text = view.row_text(absolute_row) if view is not None else Text("")
            strip = _text_to_strip(self.app.console, text, render_width)
            strip = strip.apply_style(style)
            # Pad short rows with background-only cells: they stay a
            # separate run (exact text lengths, no glyph stretching)
            # while filling the remainder like the text background.
            strip = strip.crop_extend(0, render_width, pad_style)
            strip = (
                Strip.blank(BODY_PAD_LEFT, pad_style)
                + strip
                + Strip.blank(BODY_PAD_RIGHT, pad_style)
            )
            strip = strip.crop_extend(scroll_x, scroll_x + outer_width, pad_style)
        except Exception:
            plain = ""
            if view is not None:
                try:
                    plain = view.row_plain_text(absolute_row)
                except Exception:
                    plain = ""
            strip = _plain_to_strip(plain, render_width, self.rich_style)
            try:
                strip = (
                    Strip.blank(BODY_PAD_LEFT, self.rich_style)
                    + strip
                    + Strip.blank(BODY_PAD_RIGHT, self.rich_style)
                )
                strip = strip.crop_extend(0, outer_width, self.rich_style)
            except Exception:
                pass
        self._strip_cache[key] = strip
        return strip

    def _refresh_virtual_size(self) -> None:
        """Point ``virtual_size`` at the active source without relaying out."""
        view = _owning_view(self)
        # Virtual width mirrors the full strip width (text plus baked side
        # pads), matching the old inner Static's content width.
        outer, _inner = self._strip_widths()
        width = outer
        if view is not None:
            try:
                paint_width = int(view._body_paint_width())
            except Exception:
                paint_width = 0
            if paint_width > 0:
                width = paint_width + BODY_PAD_LEFT + BODY_PAD_RIGHT
        if width <= 0:
            try:
                width = max(int(self.size.width), 1)
            except Exception:
                width = 1
        if self._overlay_text is not None:
            height = self.overlay_line_count
        elif view is not None and view._body is not None:
            try:
                height = int(view._body.total_height)
            except Exception:
                height = 0
        else:
            height = 0
        self.virtual_size = Size(width, max(height, 1))

    def on_resize(self, _event: Resize) -> None:
        view = _owning_view(self)
        if view is not None:
            view._ensure_body_layout()
            view._update_chrome_position()

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_x(old_value, new_value)
        view = _owning_view(self)
        if view is not None:
            view._after_scroll()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        view = _owning_view(self)
        if view is not None:
            view._after_scroll()


__all__ = ["BODY_PAD_LEFT", "BODY_PAD_RIGHT", "PagerBodyScroll"]

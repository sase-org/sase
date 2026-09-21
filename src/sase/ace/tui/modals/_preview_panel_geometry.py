"""Content-aware sizing glue for the preview panel modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.segment import Segment
from textual import events
from textual.containers import Container

from sase.ace.tui.util.lazy_syntax import exceeds_syntax_highlight_cap

from .preview_panel_sizing import (
    PanelGeometry,
    baseline_geometry,
    compute_panel_geometry,
    gutter_width,
    max_geometry,
    p95_line_width,
)
from .preview_search import count_wrapped_rows

if TYPE_CHECKING:
    from rich.console import RenderableType

# Named constants mirroring PreviewPanelModal TCSS.
_CONTAINER_BORDER = 2
_CONTAINER_PADDING_ROWS = 2
_CONTAINER_PADDING_COLS = 4
_TITLE_MARGIN_BOTTOM = 1
_PROPERTIES_MARGIN_BOTTOM = 1
_PROPERTIES_MAX_HEIGHT = 12
_PROPERTIES_BORDER_ROWS = 2
_PROPERTIES_PADDING_COLS = 2
_SCROLL_BORDER_ROWS = 2
_SCROLL_BORDER_COLS = 2
_SCROLL_PADDING_COLS = 2
_SCROLLBAR_GUTTER = 2
_FOOTER_HEIGHT = 3
_FOOTER_MARGIN_TOP = 1

CHROME_COLS = (
    _CONTAINER_BORDER
    + _CONTAINER_PADDING_COLS
    + _SCROLL_BORDER_COLS
    + _SCROLL_PADDING_COLS
    + _SCROLLBAR_GUTTER
)
_CONTAINER_VERTICAL = _CONTAINER_BORDER + _CONTAINER_PADDING_ROWS
_SCROLL_BORDER = _SCROLL_BORDER_ROWS
_FOOTER_OUTER = _FOOTER_HEIGHT + _FOOTER_MARGIN_TOP


def _measured_render_height(renderable: RenderableType, width: int) -> int:
    """Return the Rich row count for ``renderable`` at ``width``."""
    safe_width = max(1, width)
    console = Console(width=safe_width, force_terminal=True)
    options = console.options.update_width(safe_width)
    segments = console.render(renderable, options)
    return max(1, len(list(Segment.split_lines(segments))))


class PreviewPanelGeometryMixin:
    """Grow-only, flicker-free sizing for the preview panel container."""

    _geometry_floor: PanelGeometry | None
    _last_geometry_screen: tuple[int, int] | None

    def _preview_title_outer_rows(self, inner_width: int) -> int:
        title = self._build_title()  # type: ignore[attr-defined]
        return (
            _measured_render_height(title, max(1, inner_width)) + _TITLE_MARGIN_BOTTOM
        )

    def _preview_band_outer_rows(self, inner_width: int) -> int:
        band = self._properties_band  # type: ignore[attr-defined]
        view_mode = self._view_mode  # type: ignore[attr-defined]
        if band is None or view_mode == "properties":
            return 0
        content_width = max(1, inner_width - _PROPERTIES_PADDING_COLS)
        content_rows = _measured_render_height(band, content_width)
        outer = min(content_rows + _PROPERTIES_BORDER_ROWS, _PROPERTIES_MAX_HEIGHT)
        return outer + _PROPERTIES_MARGIN_BOTTOM

    def _preview_chrome_rows(self, container_width: int) -> int:
        inner_width = max(
            1, container_width - _CONTAINER_BORDER - _CONTAINER_PADDING_COLS
        )
        return (
            _CONTAINER_VERTICAL
            + self._preview_title_outer_rows(inner_width)
            + self._preview_band_outer_rows(inner_width)
            + _SCROLL_BORDER
            + _FOOTER_OUTER
        )

    def _preview_apply_geometry(self, *, reset_floor: bool = False) -> None:
        if not self.is_attached:  # type: ignore[attr-defined]
            return
        try:
            screen_size = self.app.size  # type: ignore[attr-defined]
        except Exception:
            return
        screen_w, screen_h = int(screen_size.width), int(screen_size.height)
        if screen_w <= 0 or screen_h <= 0:
            return
        last_screen = getattr(self, "_last_geometry_screen", None)
        if reset_floor:
            self._geometry_floor = None
        elif last_screen is not None and last_screen != (screen_w, screen_h):
            self._geometry_floor = None
        try:
            payload = self._payload  # type: ignore[attr-defined]
        except AttributeError:
            return
        content: str = payload.content
        lexer: str = payload.lexer
        baseline = baseline_geometry(screen_w, screen_h)
        maximum = max_geometry(screen_w, screen_h)

        if not content:
            logical_lines = 1
        elif content.endswith("\n"):
            logical_lines = max(1, content.count("\n"))
        else:
            logical_lines = content.count("\n") + 1
        plain = exceeds_syntax_highlight_cap(content, lexer)
        gutter = gutter_width(logical_lines, line_numbers=not plain)
        raw_p95 = p95_line_width(content)
        content_cols = raw_p95 + gutter

        # Width first so the wrapped-row count uses the final body width.
        container_width = max(
            baseline.width,
            min(CHROME_COLS + content_cols, maximum.width),
        )
        chrome_rows = self._preview_chrome_rows(container_width)
        body_width = max(1, container_width - CHROME_COLS)

        # Fast path: clearly small previews skip Rich wrapping entirely.
        if logical_lines + chrome_rows <= baseline.height:
            expanded = content.expandtabs(4).split("\n")
            widest = 0
            from rich.cells import cell_len

            for line in expanded:
                width = cell_len(line)
                if width > widest:
                    widest = width
                    if widest + gutter + CHROME_COLS > baseline.width:
                        break
            if widest + gutter + CHROME_COLS <= baseline.width:
                self._preview_set_container(baseline)
                return

        limit = max(1, maximum.height - chrome_rows)
        content_rows = count_wrapped_rows(content, body_width, lexer, limit=limit)
        geometry = compute_panel_geometry(
            screen_w=screen_w,
            screen_h=screen_h,
            content_rows=content_rows,
            content_cols=content_cols,
            chrome_rows=chrome_rows,
            chrome_cols=CHROME_COLS,
        )
        self._preview_set_container(geometry)

    def _preview_set_container(self, geometry: PanelGeometry) -> None:
        floor = self._geometry_floor
        if floor is not None:
            geometry = PanelGeometry(
                width=max(geometry.width, floor.width),
                height=max(geometry.height, floor.height),
            )
        try:
            screen_size = self.app.size  # type: ignore[attr-defined]
            self._last_geometry_screen = (
                int(screen_size.width),
                int(screen_size.height),
            )
        except Exception:
            pass
        self._geometry_floor = geometry
        if not self.is_attached:  # type: ignore[attr-defined]
            return
        try:
            container = self.query_one(  # type: ignore[attr-defined]
                "#preview-modal-container", Container
            )
        except Exception:
            return
        container.styles.width = geometry.width
        container.styles.height = geometry.height
        container.styles.max_width = None
        container.styles.max_height = None

    def _preview_schedule_ratchet(self) -> None:
        if not self.is_attached:  # type: ignore[attr-defined]
            return
        try:
            self.call_after_refresh(self._preview_grow_for_current_view)  # type: ignore[attr-defined]
        except Exception:
            return

    def _preview_grow_for_current_view(self) -> None:
        if not self.is_attached:  # type: ignore[attr-defined]
            return
        try:
            from textual.widgets import Markdown, Static

            view_mode = self._view_mode  # type: ignore[attr-defined]
            if view_mode == "rendered":
                widget = self.query_one("#preview-rendered", Markdown)  # type: ignore[attr-defined]
            elif view_mode == "properties":
                widget = self.query_one("#preview-properties-view", Static)  # type: ignore[attr-defined]
            else:
                return
            if not widget.display:
                return
            needed_rows = max(1, int(widget.outer_size.height))
            container = self.query_one("#preview-modal-container", Container)  # type: ignore[attr-defined]
            container_width = max(1, int(container.outer_size.width))
            try:
                screen_size = self.app.size  # type: ignore[attr-defined]
                screen_w, screen_h = (
                    int(screen_size.width),
                    int(screen_size.height),
                )
            except Exception:
                return
            maximum = max_geometry(screen_w, screen_h)
            # Container width stays; only grow height for the taller view.
            if container_width < 1:
                return
            chrome_rows = self._preview_chrome_rows(container_width)
            needed_container = min(chrome_rows + needed_rows, maximum.height)
            current_container = max(1, int(container.outer_size.height))
            if needed_container <= current_container:
                return
            floor = self._geometry_floor
            floor_width = floor.width if floor is not None else container_width
            self._preview_set_container(
                PanelGeometry(
                    width=max(container_width, floor_width),
                    height=needed_container,
                )
            )
        except Exception:
            return

    def on_resize(self, _event: events.Resize) -> None:
        """Recompute geometry from scratch on real screen resizes."""
        try:
            screen_size = self.app.size  # type: ignore[attr-defined]
            current = (int(screen_size.width), int(screen_size.height))
        except Exception:
            return
        if self._last_geometry_screen == current:
            return
        self._geometry_floor = None
        self._preview_apply_geometry()


__all__ = ["CHROME_COLS", "PreviewPanelGeometryMixin"]

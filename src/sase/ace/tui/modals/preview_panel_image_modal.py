"""Inline image preview modal for prompt preview."""

from __future__ import annotations

import asyncio

from rich.console import RenderableType
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.graphics import (
    image_preview,
    image_preview_size_for_viewport,
    image_render_context,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload

from .preview_panel_modal import PreviewPanelModal
from .preview_panel_sizing import max_geometry


class ImagePreviewPanelModal(PreviewPanelModal):
    """Preview reader that renders a supported image inline."""

    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__(payload)
        self._image_renderable: RenderableType | None = None
        self._image_request_id: int = 0
        self._image_requested_size: tuple[int, int] | None = None

    def _build_content(self) -> RenderableType:
        if self._image_renderable is None:
            return Text("Loading image…", style="dim italic")
        return self._image_renderable

    def _build_footer(self) -> str:
        return "Y path | % copy | Z viewer | esc close"

    def _preview_apply_geometry(self, *, reset_floor: bool = False) -> None:
        if not self.is_attached:
            return
        try:
            screen_size = self.app.size
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
        maximum = max_geometry(screen_w, screen_h)
        self._preview_set_container(maximum)
        try:
            self.call_after_refresh(self._schedule_image_render)
        except Exception:
            return

    def _schedule_image_render(self) -> None:
        if not self.is_attached:
            return
        try:
            scroll = self.query_one("#preview-scroll", VerticalScroll)
        except Exception:
            scroll = None
        try:
            content = self.query_one("#preview-content", Static)
        except Exception:
            content = None
        columns, rows = image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=content,
        )
        if (columns, rows) == self._image_requested_size:
            return
        self._image_requested_size = (columns, rows)
        self._image_request_id += 1
        request_id = self._image_request_id
        spawn_pump_free_task(
            self,
            self._render_image(request_id, columns, rows),
            name="sase-preview-render-image",
            registry_attr="_pump_free_async_tasks",
        )

    async def _render_image(self, request_id: int, columns: int, rows: int) -> None:
        path = self._payload.source_path
        if path is None:
            return
        renderable = await asyncio.to_thread(
            image_preview,
            path,
            image_render_context(),
            columns=columns,
            rows=rows,
            fallback_hint="Press Z to open it in the artifact viewer",
        )
        if request_id != self._image_request_id or not self.is_attached:
            return
        self._image_renderable = renderable
        if not self.is_attached:
            return
        try:
            self.query_one("#preview-content", Static).update(self._build_content())
        except Exception:
            return

    def action_open_search(self) -> None:
        self.notify(
            "Search is not available for image previews",
            severity="warning",
        )

    def action_copy_contents(self) -> None:
        self.notify(
            "Image previews have no text to copy; press Y to copy the path",
            severity="warning",
        )

    def action_open_in_editor(self) -> None:
        self.notify(
            "Images open in the artifact viewer; press Z",
            severity="warning",
        )


__all__ = ["ImagePreviewPanelModal"]

"""Inline, still-frame video preview for prompt file paths."""

from __future__ import annotations

import asyncio

from rich.console import RenderableType
from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.graphics import (
    VideoPreviewInfo,
    format_video_preview_position,
    load_video_preview_info,
    video_preview_frame,
    video_preview_timestamp,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload

from .preview_panel_image_modal import ImagePreviewPanelModal


class VideoPreviewPanelModal(ImagePreviewPanelModal):
    """Preview a video as a large still frame with decile navigation."""

    BINDINGS = [
        ("h", "step_backward", "Back 10%"),
        ("left", "step_backward", "Back 10%"),
        ("l", "step_forward", "Forward 10%"),
        ("right", "step_forward", "Forward 10%"),
        ("0", "jump_decile_0", "Jump to 0%"),
        ("1", "jump_decile_1", "Jump to 10%"),
        ("2", "jump_decile_2", "Jump to 20%"),
        ("3", "jump_decile_3", "Jump to 30%"),
        ("4", "jump_decile_4", "Jump to 40%"),
        ("5", "jump_decile_5", "Jump to 50%"),
        ("6", "jump_decile_6", "Jump to 60%"),
        ("7", "jump_decile_7", "Jump to 70%"),
        ("8", "jump_decile_8", "Jump to 80%"),
        ("9", "jump_decile_9", "Jump to 90%"),
    ]

    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__(payload)
        self._video_info: VideoPreviewInfo | None = None
        self._video_probe_complete = False
        self._video_probe_request_id = 0
        self._video_decile = 0
        self._video_frame_in_flight = False
        self._video_displayed_frame: tuple[int, int, int] | None = None

    def _build_content(self) -> RenderableType:
        if self._image_renderable is None:
            return Text("Loading video…", style="dim italic")
        return self._image_renderable

    def _build_footer(self) -> str:
        parts: list[str] = []
        if self._video_duration_known():
            parts.extend(("h/l ±10%", "0-9 jump"))
        parts.extend(("Y path", "% copy", "Z inspect/play", "esc close"))
        return " | ".join(parts)

    def on_mount(self) -> None:
        super().on_mount()
        path = self._payload.source_path
        if path is None:
            return
        self._video_probe_request_id += 1
        request_id = self._video_probe_request_id
        spawn_pump_free_task(
            self,
            self._load_video_info(request_id, path),
            name="sase-preview-probe-video",
            registry_attr="_pump_free_async_tasks",
        )

    async def _load_video_info(self, request_id: int, path: str) -> None:
        info = await asyncio.to_thread(load_video_preview_info, path)
        if not self.is_attached or request_id != self._video_probe_request_id:
            return
        self._video_info = info
        self._video_probe_complete = True
        self._update_video_properties()
        self._update_video_footer()

    def _schedule_image_render(self) -> None:
        if not self.is_attached:
            return
        columns, rows = self._preview_render_size()
        size = (columns, rows)
        if size == self._image_requested_size:
            if self._video_displayed_frame == (
                self._video_decile,
                columns,
                rows,
            ):
                return
        else:
            self._image_requested_size = size
            self._image_request_id += 1
        self._start_latest_video_frame(columns, rows)

    def _start_latest_video_frame(self, columns: int, rows: int) -> None:
        if self._video_frame_in_flight or not self.is_attached:
            return
        path = self._payload.source_path
        if path is None:
            return
        self._video_frame_in_flight = True
        request_id = self._image_request_id
        decile = self._video_decile
        at_seconds = video_preview_timestamp(
            decile,
            self._video_duration_seconds(),
        )
        task = spawn_pump_free_task(
            self,
            self._render_video_frame(
                request_id,
                decile,
                at_seconds,
                columns,
                rows,
                path,
            ),
            name="sase-preview-render-video-frame",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._video_frame_in_flight = False

    async def _render_video_frame(
        self,
        request_id: int,
        decile: int,
        at_seconds: float,
        columns: int,
        rows: int,
        path: str,
    ) -> None:
        try:
            renderable = await asyncio.to_thread(
                video_preview_frame,
                path,
                at_seconds,
                None,
                columns=columns,
                rows=rows,
            )
        finally:
            self._video_frame_in_flight = False

        if not self.is_attached:
            return
        if request_id != self._image_request_id:
            self._schedule_image_render()
            return
        if self._preview_render_size() != (columns, rows):
            self._invalidate_image_render()
            self._schedule_image_render()
            return
        self._video_displayed_frame = (decile, columns, rows)
        self._update_image_renderable(renderable)

    def _video_duration_seconds(self) -> float | None:
        info = self._video_info
        if info is None:
            return None
        return info.duration_seconds

    def _video_duration_known(self) -> bool:
        duration = self._video_duration_seconds()
        return duration is not None and duration > 0

    def _update_video_properties(self) -> None:
        if not self.is_attached:
            return
        info = self._video_info
        lines: list[RenderableType] = []
        summary = info.summary if info is not None else None
        notice = info.notice if info is not None else None
        if summary:
            lines.append(Text(summary, style="bold #AFD7FF"))
        elif notice:
            lines.append(Text("Video metadata unavailable", style="dim italic"))
        if notice:
            lines.append(Text(notice, style="dim italic"))
        lines.append(
            Text(
                format_video_preview_position(
                    self._video_decile,
                    self._video_duration_seconds(),
                ),
                style="dim",
            )
        )
        band: RenderableType = lines[0] if len(lines) == 1 else Group(*lines)
        self._properties_band = band
        try:
            widget = self.query_one("#preview-properties", Static)
            widget.update(band)
            widget.display = True
        except Exception:
            return

    def _update_video_footer(self) -> None:
        if not self.is_attached:
            return
        try:
            self.query_one("#preview-footer", Static).update(self._build_footer())
        except Exception:
            return

    def _step_video(self, delta: int) -> None:
        if not self._video_duration_known():
            self.notify(
                "Video duration unknown; press Z for the artifact viewer",
                severity="warning",
            )
            return
        self._set_video_decile(max(0, min(9, self._video_decile + delta)))

    def _set_video_decile(self, decile: int) -> None:
        if decile == self._video_decile:
            return
        self._video_decile = decile
        self._video_displayed_frame = None
        self._invalidate_image_render()
        self._update_video_properties()
        self._schedule_image_render()

    def action_step_backward(self) -> None:
        self._step_video(-1)

    def action_step_forward(self) -> None:
        self._step_video(1)

    def action_jump_decile_0(self) -> None:
        self._jump_to_video_decile(0)

    def action_jump_decile_1(self) -> None:
        self._jump_to_video_decile(1)

    def action_jump_decile_2(self) -> None:
        self._jump_to_video_decile(2)

    def action_jump_decile_3(self) -> None:
        self._jump_to_video_decile(3)

    def action_jump_decile_4(self) -> None:
        self._jump_to_video_decile(4)

    def action_jump_decile_5(self) -> None:
        self._jump_to_video_decile(5)

    def action_jump_decile_6(self) -> None:
        self._jump_to_video_decile(6)

    def action_jump_decile_7(self) -> None:
        self._jump_to_video_decile(7)

    def action_jump_decile_8(self) -> None:
        self._jump_to_video_decile(8)

    def action_jump_decile_9(self) -> None:
        self._jump_to_video_decile(9)

    def _jump_to_video_decile(self, decile: int) -> None:
        if not self._video_duration_known():
            self.notify(
                "Video duration unknown; press Z for the artifact viewer",
                severity="warning",
            )
            return
        self._set_video_decile(decile)

    def action_open_search(self) -> None:
        self.notify("Search is not available for video previews", severity="warning")

    def action_copy_contents(self) -> None:
        self.notify(
            "Video previews have no text to copy; press Y to copy the path",
            severity="warning",
        )

    def action_open_in_editor(self) -> None:
        self.notify("Videos open in the artifact viewer; press Z", severity="warning")


__all__ = ["VideoPreviewPanelModal"]

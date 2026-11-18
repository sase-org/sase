"""Video inspect session state and background frame service.

Owns the playhead, layout, and background scrub/storyboard work. Rendering,
key handling, and the public entrypoint live in
:mod:`sase.ace.tui.graphics._viewer_loop_video_view`.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._viewer_kitty_capability import kitty_graphics_capable
from ._viewer_loop_terminal import (
    artifact_image_area,
    kitten_icat_clear_command,
    run_command as default_run_command,
    viewer_kitten_icat_command,
)
from ._viewer_loop_types import ArtifactVideoPlaybackConfig
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)
from ._viewer_video_frames import (
    FrameExtractResult,
    ScrubTrack,
    StoryboardResult,
    artifact_video_cache_dir,
    build_storyboard,
    content_digest_for_path,
    extract_frame,
    metadata_for_frame_service,
    scrub_fps_for_duration,
    start_scrub_track,
)
from ._viewer_video_media import VideoMetadata, terminal_pixel_size
from ._viewer_loop_video_common import (
    ReadKey,
    RunCommand,
    SelectPane,
    ToggleZoom,
    VideoInspectLayout,
    compute_inspect_layout,
)
from ._viewer_video_input import (
    enter_quiet_terminal,
    exit_quiet_terminal,
    read_inspect_key,
)

_DEFAULT_SOURCE_FPS = 30.0

_VideoInspectAction = Literal["next", "previous", "quit", "return_pane"]


@dataclass(frozen=True)
class VideoInspectOutcome:
    """Result of the inspect-first video view, consumed by the sequence loop."""

    action: _VideoInspectAction = "quit"
    returncode: int = 0
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()


class VideoInspectSessionBase:
    def __init__(
        self,
        spec: ArtifactFileViewSpec,
        *,
        video_config: ArtifactVideoPlaybackConfig,
        image_area: ArtifactFileImageArea | None,
        read_key: ReadKey | None,
        run_command: RunCommand | None,
        artifact_index: int,
        artifact_count: int,
        return_pane_id: str | None,
        select_pane: SelectPane | None,
        tmux_zoom_available: bool,
        toggle_zoom: ToggleZoom | None,
    ) -> None:
        self.spec = spec
        self.path = Path(spec.path).expanduser().resolve(strict=False)
        self.video_config = video_config
        self._fixed_area = image_area
        self._using_default_reader = read_key is None
        self._read = read_key or read_inspect_key
        self._quiet_saved: list | None = None
        self._last_status_text: str | None = None
        self._last_status_row: int | None = None
        self._run = run_command or default_run_command
        self.artifact_index = artifact_index
        self.artifact_count = artifact_count
        self.return_pane_id = return_pane_id
        self._select = select_pane
        self.zoom_available = tmux_zoom_available
        self._toggle_zoom = toggle_zoom
        self.cache = artifact_video_cache_dir()
        self.metadata: VideoMetadata | None = None
        self.scrub: ScrubTrack | None = None
        self.at = 0.0
        self.storyboard_enabled = True
        self.notice: str | None = None
        self._storyboard_result: StoryboardResult | None = None
        self._storyboard_shown = False
        self._storyboard_thread: threading.Thread | None = None
        self._first_visual = False
        self._want_exact = False
        self.cell_fallback = not kitty_graphics_capable()
        self._term_size = shutil.get_terminal_size(fallback=(80, 24))
        self.layout = self._compute_layout()

    @property
    def duration(self) -> float | None:
        if self.metadata is None:
            return None
        return self.metadata.duration_seconds

    @property
    def source_fps(self) -> float:
        if self.metadata is not None and self.metadata.fps and self.metadata.fps > 0:
            return self.metadata.fps
        return _DEFAULT_SOURCE_FPS

    def _enter_quiet(self) -> None:
        if not self._using_default_reader:
            return
        if self._quiet_saved is not None:
            return
        self._quiet_saved = enter_quiet_terminal()

    def _exit_quiet(self) -> None:
        exit_quiet_terminal(self._quiet_saved)
        self._quiet_saved = None

    def _invalidate_status_cache(self) -> None:
        self._last_status_text = None
        self._last_status_row = None

    def cleanup(self) -> None:
        if self.scrub is not None:
            self.scrub.cancel()
        thread = self._storyboard_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.2)
        if shutil.which("kitten") is not None:
            try:
                self._run(kitten_icat_clear_command())
            except (OSError, TypeError, ValueError, subprocess.SubprocessError):
                pass
        self._exit_quiet()

    def _prepare(self) -> None:
        if content_digest_for_path(self.path) is None:
            self.notice = "could not read video file"
        if shutil.which("ffprobe") is None:
            self.notice = "ffprobe executable not found: video metadata unavailable"
        elif shutil.which("ffmpeg") is None:
            self.notice = "ffmpeg executable not found: video still unavailable"
        self.metadata = metadata_for_frame_service(self.path, cache_dir=self.cache)

    def _start_background(self) -> None:
        duration = self.duration
        fps = scrub_fps_for_duration(duration)
        self.scrub = start_scrub_track(
            self.path,
            duration,
            self._frame_max_px(),
            cache_dir=self.cache,
            metadata=self.metadata,
            scrub_fps=fps,
        )
        self._start_storyboard()

    def _start_storyboard(self) -> None:
        if self.cell_fallback:
            return
        if not self.layout.show_storyboard or self.layout.storyboard is None:
            return
        duration = self.duration
        if duration is None or duration <= 0:
            return
        strip = self.layout.storyboard
        pixel_width, pixel_height = terminal_pixel_size()
        cols = max(1, self.layout.columns)
        rows = max(1, self.layout.pane_rows)
        strip_width = max(1, int(pixel_width * strip.columns / cols))
        strip_height = max(1, int(pixel_height * strip.rows / rows))

        def _work() -> None:
            self._storyboard_result = build_storyboard(
                self.path,
                duration,
                self._frame_max_px(),
                strip_width_px=strip_width,
                strip_height_px=strip_height,
                cache_dir=self.cache,
                scrub_track=self.scrub,
            )

        self._storyboard_thread = threading.Thread(
            target=_work, name="sase-video-storyboard", daemon=True
        )
        self._storyboard_thread.start()

    def _compute_layout(self) -> VideoInspectLayout:
        if self._fixed_area is not None:
            area = self._fixed_area
            pane_rows = area.top + area.rows + 2
        else:
            area = artifact_image_area(self._term_size)
            pane_rows = int(self._term_size.lines)
        return compute_inspect_layout(
            area,
            storyboard_enabled=self.storyboard_enabled and not self.cell_fallback,
            pane_rows=pane_rows,
        )

    def _frame_max_px(self) -> int:
        pixel_width, _ = terminal_pixel_size()
        columns = max(1, self.layout.columns)
        return max(1, int(pixel_width * self.layout.frame.columns / columns))

    def _frame_at(self, at_seconds: float, *, exact: bool) -> FrameExtractResult:
        if not exact and self.scrub is not None:
            nearest = self.scrub.nearest(at_seconds)
            if nearest is not None:
                return FrameExtractResult(path=nearest, cached=True, error=None)
        return extract_frame(
            self.path, at_seconds, self._frame_max_px(), cache_dir=self.cache
        )

    def _icat(self, page: Path, area: ArtifactFileImageArea, image_id: int) -> bool:
        """Display *page* with kitten icat; return True when it fell back."""

        if shutil.which("kitten") is None:
            self.notice = "kitten executable not found: video frame cannot display"
            self.cell_fallback = True
            return True
        command = viewer_kitten_icat_command(page, area, image_id=image_id)
        result = self._run(command)
        if getattr(result, "returncode", 0) != 0:
            self.cell_fallback = True
            self.notice = (
                f"kitten icat failed with exit code {getattr(result, 'returncode', 1)}"
            )
            return True
        return False

    def _restart_storyboard(self) -> None:
        self._storyboard_shown = False
        self._storyboard_result = None
        self._start_storyboard()


__all__ = [
    "VideoInspectOutcome",
    "VideoInspectSessionBase",
]

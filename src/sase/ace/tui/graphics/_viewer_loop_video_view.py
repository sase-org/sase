"""Video inspect rendering, key handling, and entrypoint.

Implements the inspect-first view on top of
:mod:`sase.ace.tui.graphics._viewer_loop_video_session`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ._viewer_video_motion import (
    artifact_video_motion_command,
    build_native_open_command,
    motion_playback_block_reason,
    normalize_video_backend,
)
from ._viewer_loop_terminal import (
    _FOOTER_COLOR,
    _FOOTER_RESET,
    _RETURN_TO_ACE_KEY,
    clear_terminal,
    print_artifact_header,
    print_artifact_warning,
)
from ._viewer_loop_types import ArtifactVideoPlaybackConfig
from ._viewer_trace import emit_child_span, mark_first_visual
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)
from ._viewer_video_frames import enforce_cache_budget
from ._viewer_video_media import format_video_metadata_summary
from ._viewer_loop_video_common import (
    KeySource,
    ReadKey,
    RunCommand,
    SelectPane,
    ToggleZoom,
    clamp_timestamp,
    decile_timestamp,
    format_inspect_status,
    snap_timestamp,
    step_timestamp,
)
from ._viewer_loop_video_session import (
    VideoInspectOutcome,
    VideoInspectSessionBase,
)

_FRAME_IMAGE_ID = 1
_CELL_FALLBACK_BANNER = "terminal without kitty graphics: cell preview"
_STORYBOARD_IMAGE_ID = 2
_POLL_TIMEOUT_SECONDS = 0.05
_STEP_FORWARD = frozenset({"l", "right"})
_STEP_BACK = frozenset({"h", "left"})
_FRAME_FORWARD = frozenset({"."})
_FRAME_BACK = frozenset({","})
_COALESCE_KEYS = _STEP_FORWARD | _STEP_BACK | _FRAME_FORWARD | _FRAME_BACK


def run_video_inspect(
    spec: ArtifactFileViewSpec,
    *,
    cache_root: str | Path,
    video_config: ArtifactVideoPlaybackConfig,
    image_area: ArtifactFileImageArea | None = None,
    read_key: ReadKey | None = None,
    run_command: RunCommand | None = None,
    artifact_index: int = 0,
    artifact_count: int = 1,
    return_pane_id: str | None = None,
    select_pane: SelectPane | None = None,
    tmux_zoom_available: bool = False,
    toggle_zoom: ToggleZoom | None = None,
) -> VideoInspectOutcome:
    """Run the inspect-first video view until a sequence-loop outcome."""

    _ = cache_root
    session = _VideoInspectSession(
        spec,
        video_config=video_config,
        image_area=image_area,
        read_key=read_key,
        run_command=run_command,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
        return_pane_id=return_pane_id,
        select_pane=select_pane,
        tmux_zoom_available=tmux_zoom_available,
        toggle_zoom=toggle_zoom,
    )
    try:
        return session.run()
    finally:
        session.cleanup()


class _VideoInspectSession(VideoInspectSessionBase):
    def run(self) -> VideoInspectOutcome:
        if not self.path.exists():
            warning = ArtifactFileViewerWarning(
                "artifact_not_found", "Artifact file not found"
            )
            return VideoInspectOutcome(action="quit", returncode=1, warnings=(warning,))
        if not self.path.is_file():
            warning = ArtifactFileViewerWarning(
                "artifact_not_file", "Artifact path is not a file"
            )
            return VideoInspectOutcome(action="quit", returncode=1, warnings=(warning,))
        self._enter_quiet()
        self._prepare()
        self._paint(full=True)
        self._start_background()
        self._poll_background()
        keys = KeySource(self._read)
        while True:
            self._poll_background()
            if self._fixed_area is None:
                self._poll_resize()
            key = keys.get(timeout=_POLL_TIMEOUT_SECONDS)
            if key is None:
                continue
            if key in _COALESCE_KEYS:
                burst = self._coalesce(keys, key)
                self._apply_step_keys(burst)
                self._print_status()
                self._render_frame(span=True)
                continue
            outcome = self._handle_key(key)
            if outcome is not None:
                return outcome

    def _poll_background(self) -> None:
        if (
            self._storyboard_result is not None
            and self._storyboard_result.ok
            and not self._storyboard_shown
            and self.layout.show_storyboard
        ):
            self._render_storyboard()
        self._print_status()

    def _poll_resize(self) -> None:
        size = shutil.get_terminal_size(fallback=(80, 24))
        if (size.columns, size.lines) == (
            self._term_size.columns,
            self._term_size.lines,
        ):
            return
        self._term_size = size
        self.layout = self._compute_layout()
        self._restart_storyboard()
        self._paint(full=True)

    def _paint(self, *, full: bool) -> None:
        if full:
            self._invalidate_status_cache()
            clear_terminal()
            summary = (
                format_video_metadata_summary(self.metadata)
                if self.metadata is not None
                else None
            )
            media_label = f"\u25b6 Video {summary}" if summary else "\u25b6 Video"
            print_artifact_header(
                self.spec,
                page_index=0,
                page_count=1,
                artifact_index=self.artifact_index,
                artifact_count=self.artifact_count,
                media_label=media_label,
            )
        self._render_frame(span=False)
        if self._storyboard_result is not None and self._storyboard_result.ok:
            self._render_storyboard()
        self._print_status()
        self._print_footer()

    def _render_frame(self, *, span: bool) -> None:
        result = self._frame_at(self.at, exact=self._want_exact)
        self._want_exact = False
        if result.ok and result.path is not None:
            if self.cell_fallback:
                self._render_frame_cells(result.path)
            elif self._icat(result.path, self.layout.frame, _FRAME_IMAGE_ID):
                self.layout = self._compute_layout()
                self._restart_storyboard()
                self._paint(full=True)
                if span:
                    emit_child_span("key_to_frame", mode="video", at_seconds=self.at)
                return
            if not self._first_visual:
                mark_first_visual("video")
                self._first_visual = True
        elif result.error:
            self.notice = result.error
        if span:
            emit_child_span("key_to_frame", mode="video", at_seconds=self.at)

    def _render_storyboard(self) -> None:
        result = self._storyboard_result
        area = self.layout.storyboard
        if result is None or not result.ok or result.path is None or area is None:
            return
        self._icat(result.path, area, _STORYBOARD_IMAGE_ID)
        if not self._storyboard_shown:
            emit_child_span("storyboard_ready", mode="video")
            enforce_cache_budget(self.cache)
        self._storyboard_shown = True

    def _render_frame_cells(self, frame: Path) -> None:
        """Render *frame* as Unicode cells for terminals without kitty graphics."""

        from rich.console import Console

        from .capability import image_render_context
        from .cell import CellImageError, CellImageRenderable

        area = self.layout.frame
        try:
            renderable = CellImageRenderable.from_path(
                str(frame),
                columns=max(1, area.columns),
                rows=max(1, area.rows),
                truecolor=image_render_context().truecolor,
            )
        except (CellImageError, OSError) as exc:
            if self.notice is None:
                self.notice = f"cell preview unavailable: {exc}"
            return
        sys.stdout.write(f"\x1b[{max(0, area.top) + 1};1H")
        sys.stdout.flush()
        Console(width=max(1, area.columns)).print(renderable, end="")

    def _print_status(self) -> None:
        progress = None if self.scrub is None else self.scrub.progress
        notice: str | None
        if self.cell_fallback:
            notice = _CELL_FALLBACK_BANNER
            if self.notice:
                notice = f"{notice} ({self.notice})"
        else:
            notice = self.notice
        text = format_inspect_status(
            self.at,
            self.duration,
            scrub_progress=progress,
            notice=notice,
            bar_width=10 if self.cell_fallback else 22,
        )
        line = text[: self.layout.columns].ljust(self.layout.columns)
        row = self.layout.status_row
        if line == self._last_status_text and row == self._last_status_row:
            return
        self._last_status_text = line
        self._last_status_row = row
        sys.stdout.write(f"\x1b[{row};1H{line}")
        sys.stdout.flush()

    def _print_footer(self) -> None:
        parts = [
            "h/l: seek",
            ",/.: frame",
            "0-9: jump",
            "s: board",
            "space: play",
            "o: open",
            "r: refresh",
        ]
        if self.zoom_available:
            parts.append("z: zoom")
        if self.artifact_index < self.artifact_count - 1:
            parts.append("n: next")
        if self.artifact_index > 0:
            parts.append("p: prev")
        if self.return_pane_id:
            parts.append("<tab>: focus SASE TUI")
        parts.append("q: quit")
        prompt = "  ".join(parts)
        if len(prompt) > self.layout.columns:
            prompt = prompt[: self.layout.columns]
        sys.stdout.write(
            f"\x1b[{self.layout.footer_row};1H"
            f"{_FOOTER_RESET}{_FOOTER_COLOR}{prompt}{_FOOTER_RESET}"
        )
        sys.stdout.flush()

    def _coalesce(self, keys: KeySource, first: str) -> list[str]:
        burst = [first]
        while True:
            nxt = keys.get(timeout=0)
            if nxt is None:
                break
            if nxt in _COALESCE_KEYS:
                burst.append(nxt)
                continue
            keys.unread(nxt)
            break
        return burst

    def _apply_step_keys(self, burst: Sequence[str]) -> None:
        snap = False
        exact = False
        for key in burst:
            if key in _STEP_FORWARD:
                self.at = step_timestamp(self.at, 1.0, self.duration)
                snap = True
            elif key in _STEP_BACK:
                self.at = step_timestamp(self.at, -1.0, self.duration)
                snap = True
            elif key in _FRAME_FORWARD:
                self.at = step_timestamp(self.at, 1.0 / self.source_fps, self.duration)
                exact = True
            elif key in _FRAME_BACK:
                self.at = step_timestamp(self.at, -1.0 / self.source_fps, self.duration)
                exact = True
        if snap and not exact:
            self.at = clamp_timestamp(
                snap_timestamp(self.at, self.scrub), self.duration
            )
        self._want_exact = exact

    def _handle_key(self, key: str) -> VideoInspectOutcome | None:
        if key == "q":
            clear_terminal()
            return VideoInspectOutcome()
        if key == _RETURN_TO_ACE_KEY and self.return_pane_id:
            if self._select is not None:
                selected = self._select(self.return_pane_id)
                if not selected.ok:
                    return VideoInspectOutcome(
                        action="quit",
                        returncode=1,
                        warnings=selected.warnings,
                    )
            return None
        if key == "n" and self.artifact_index < self.artifact_count - 1:
            return VideoInspectOutcome(action="next")
        if key == "p" and self.artifact_index > 0:
            return VideoInspectOutcome(action="previous")
        if key == "s":
            self.storyboard_enabled = not self.storyboard_enabled
            self.layout = self._compute_layout()
            self._restart_storyboard()
            self._paint(full=True)
            return None
        if key == "r":
            self.notice = None
            self._want_exact = True
            self._paint(full=True)
            return None
        if key == "z" and self.zoom_available and self._toggle_zoom is not None:
            zoomed = self._toggle_zoom()
            if not zoomed.ok:
                return VideoInspectOutcome(
                    action="quit", returncode=1, warnings=zoomed.warnings
                )
            if self._fixed_area is None:
                self._term_size = shutil.get_terminal_size(fallback=(80, 24))
            self.layout = self._compute_layout()
            self._restart_storyboard()
            self._paint(full=True)
            return None
        if key == " ":
            self._play_motion()
            return None
        if key == "o":
            self._open_native()
            return None
        if len(key) == 1 and key.isdigit():
            self.at = decile_timestamp(int(key), self.duration)
            self._print_status()
            self._render_frame(span=True)
            return None
        return None

    def _play_motion(self) -> None:
        reason = motion_playback_block_reason(self.video_config)
        if reason is not None:
            self.notice = reason
            self._print_status()
            if (
                normalize_video_backend(self.video_config.backend) == "mpv"
                and shutil.which("mpv") is None
            ):
                print_artifact_warning(
                    ArtifactFileViewerWarning(
                        "missing_mpv",
                        "mpv is not installed: in-pane motion unavailable",
                        tool="mpv",
                    )
                )
            return
        command = artifact_video_motion_command(
            self.path,
            self.layout.frame,
            self.video_config,
            at_seconds=self.at,
        )
        backend = normalize_video_backend(self.video_config.backend)
        emit_child_span(
            "motion_start", mode="video", backend=backend, at_seconds=self.at
        )
        quiet_was_active = self._quiet_saved is not None
        if quiet_was_active:
            self._exit_quiet()
        try:
            result = self._run(command)
        finally:
            if quiet_was_active:
                self._enter_quiet()
        failed = getattr(result, "returncode", 0) != 0
        if failed:
            self.notice = (
                f"mpv failed with exit code {getattr(result, 'returncode', 1)}"
            )
        self._paint(full=True)
        if failed:
            print_artifact_warning(
                ArtifactFileViewerWarning(
                    "mpv_failed",
                    self.notice or "mpv failed",
                    tool="mpv",
                )
            )

    def _open_native(self) -> None:
        argv, notice = build_native_open_command(self.path, self.video_config)
        if argv is None:
            self.notice = notice or "no native player available here"
            self._print_status()
            return
        try:
            _spawn_detached(argv)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.notice = f"native player failed to start: {exc}"
            self._print_status()
            return
        self.notice = f"opened in native player: {' '.join(argv[:1])}"
        self._print_status()


def _spawn_detached(argv: Sequence[str]) -> None:
    """Spawn a native player detached from the viewer pane process."""

    subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


__all__ = [
    "run_video_inspect",
]

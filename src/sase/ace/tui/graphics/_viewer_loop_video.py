"""Inspect-first video view for the terminal artifact viewer.

Opening a video shows a frame, a decile storyboard, and a status line.
Motion is opt-in on space; the sequence loop consumes the inspect outcome.
"""

from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
import termios
import threading
import tty
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ._viewer_loop_media import (
    artifact_video_player_command,
    video_still_preview_required,
)
from ._viewer_loop_terminal import (
    _FOOTER_COLOR,
    _FOOTER_RESET,
    _MIN_IMAGE_ROWS,
    _RETURN_TO_ACE_KEY,
    artifact_image_area,
    clear_terminal,
    kitten_icat_clear_command,
    print_artifact_header,
    print_artifact_warning,
    run_command as default_run_command,
    viewer_kitten_icat_command,
)
from ._viewer_loop_types import ArtifactVideoPlaybackConfig
from ._viewer_trace import emit_child_span, mark_first_visual
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerResult,
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
    enforce_cache_budget,
    extract_frame,
    metadata_for_frame_service,
    scrub_fps_for_duration,
    start_scrub_track,
)
from ._viewer_video_media import (
    VideoMetadata,
    format_video_metadata_summary,
    terminal_pixel_size,
)

_FRAME_IMAGE_ID = 1
_STORYBOARD_IMAGE_ID = 2
_STORYBOARD_MIN_ROWS = 5
_STORYBOARD_MIN_PANE_ROWS = 20
_DEFAULT_SOURCE_FPS = 30.0
_POLL_TIMEOUT_SECONDS = 0.05
_MOTION_UNAVAILABLE = "in-pane playback is unavailable here — scrub with h/l or 0–9"
_STEP_FORWARD = frozenset({"l", "right"})
_STEP_BACK = frozenset({"h", "left"})
_FRAME_FORWARD = frozenset({"."})
_FRAME_BACK = frozenset({","})
_COALESCE_KEYS = _STEP_FORWARD | _STEP_BACK | _FRAME_FORWARD | _FRAME_BACK
_INSPECT_ESC_TIMEOUT_SECONDS = 0.03
_ARROW_KEY_SEQUENCES = {
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1bOC": "right",
    "\x1bOD": "left",
}

ReadKey = Callable[..., str | None]
RunCommand = Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
SelectPane = Callable[[str], ArtifactFileViewerResult]
ToggleZoom = Callable[[], ArtifactFileViewerResult]
_VideoInspectAction = Literal["next", "previous", "quit", "return_pane"]


@dataclass(frozen=True)
class _VideoInspectOutcome:
    """Result of the inspect-first video view, consumed by the sequence loop."""

    action: _VideoInspectAction = "quit"
    returncode: int = 0
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()


def _decode_inspect_key(sequence: str) -> str:
    """Map a raw inspect-loop byte sequence onto a key name."""

    if sequence in _ARROW_KEY_SEQUENCES:
        return _ARROW_KEY_SEQUENCES[sequence]
    return sequence


def _completed_inspect_escape(sequence: str) -> str | None:
    mapped = _ARROW_KEY_SEQUENCES.get(sequence)
    if mapped is not None:
        return mapped
    if sequence.startswith("\x1b[") and len(sequence) >= 3 and sequence[-1].isalpha():
        return _decode_inspect_key(sequence)
    if sequence.startswith("\x1bO") and len(sequence) >= 3:
        return _decode_inspect_key(sequence)
    return None


def _assemble_inspect_key(
    read_chunk: Callable[[float | None], bytes | None],
    *,
    timeout: float | None = 0.05,
    esc_timeout: float = _INSPECT_ESC_TIMEOUT_SECONDS,
) -> str | None:
    """Read one inspect key, assembling arrow escapes split across chunks.

    ``read_chunk(wait)`` returns the next bytes, or ``None`` when *wait*
    elapses. A leading ESC waits *esc_timeout* for the rest of a CSI/SS3
    sequence so a lone Escape does not steal the next key.
    """

    first = read_chunk(timeout)
    if not first:
        return None
    sequence = first.decode(errors="ignore")
    if not sequence:
        return None
    if not sequence.startswith("\x1b"):
        return sequence[:1]
    while True:
        completed = _completed_inspect_escape(sequence)
        if completed is not None:
            return completed
        more = read_chunk(esc_timeout)
        if not more:
            break
        sequence += more.decode(errors="ignore")
    return _decode_inspect_key(sequence)


def _read_inspect_key(*, timeout: float | None = 0.05) -> str | None:
    """Nonblocking, escape-aware stdin reader for the video inspect loop."""

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
    except (OSError, termios.error, ValueError):
        return None
    try:
        tty.setraw(fd)

        def _read_chunk(wait: float | None) -> bytes | None:
            ready, _, _ = select.select([fd], [], [], wait)
            if not ready:
                return None
            return os.read(fd, 1)

        return _assemble_inspect_key(_read_chunk, timeout=timeout)
    except (OSError, termios.error, ValueError):
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@dataclass(frozen=True)
class _VideoInspectLayout:
    """Cell geometry for the inspect frame, storyboard, status, and footer."""

    frame: ArtifactFileImageArea
    storyboard: ArtifactFileImageArea | None
    status_row: int
    footer_row: int
    columns: int
    pane_rows: int
    show_storyboard: bool


def _clamp_timestamp(at_seconds: float, duration_seconds: float | None) -> float:
    """Clamp *at_seconds* into ``[0, duration]``, or ``[0, inf)`` when unknown."""

    at = max(0.0, float(at_seconds))
    if duration_seconds is not None and duration_seconds >= 0:
        at = min(at, duration_seconds)
    return at


def _decile_timestamp(digit: int, duration_seconds: float | None) -> float:
    """Return the timestamp for jump key ``0``–``9``."""

    if duration_seconds is None or duration_seconds <= 0:
        return 0.0
    return _clamp_timestamp(digit * duration_seconds / 10.0, duration_seconds)


def _snap_timestamp(at_seconds: float, scrub: ScrubTrack | None) -> float:
    """Snap *at_seconds* onto a completed scrub track, else leave it exact."""

    if scrub is None or not scrub.done or scrub.fps <= 0:
        return at_seconds
    frames = scrub.frame_paths
    if not frames:
        return at_seconds
    index = int(round(at_seconds * scrub.fps))
    index = max(0, min(index, len(frames) - 1))
    return index / scrub.fps


def _step_timestamp(
    at_seconds: float,
    delta_seconds: float,
    duration_seconds: float | None,
    *,
    scrub: ScrubTrack | None = None,
    snap: bool = False,
) -> float:
    """Apply a seek delta and optionally snap onto the scrub track."""

    target = _clamp_timestamp(at_seconds + delta_seconds, duration_seconds)
    if snap:
        return _clamp_timestamp(_snap_timestamp(target, scrub), duration_seconds)
    return target


def _format_inspect_timestamp(at_seconds: float) -> str:
    """Format a playhead as ``mm:ss.d``."""

    total = max(0.0, float(at_seconds))
    minutes = int(total // 60)
    seconds = total - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def _format_inspect_status(
    at_seconds: float,
    duration_seconds: float | None,
    *,
    scrub_progress: float | None = None,
    notice: str | None = None,
    bar_width: int = 22,
) -> str:
    """Build the inspect status line: times, position bar, optional scrub %."""

    current = _format_inspect_timestamp(at_seconds)
    total = (
        _format_inspect_timestamp(duration_seconds)
        if duration_seconds is not None
        else "--:--.-"
    )
    if duration_seconds is None or duration_seconds <= 0:
        fraction = 0.0
    else:
        fraction = min(1.0, max(0.0, at_seconds / duration_seconds))
    inner = max(1, bar_width - 2)
    filled = min(inner - 1, int(fraction * inner))
    bar = "[" + ("=" * filled) + ">" + ("-" * (inner - filled - 1)) + "]"
    line = f"{current} / {total}  {bar}"
    if scrub_progress is not None and 0.0 <= scrub_progress < 1.0:
        line += f"  scrub {int(scrub_progress * 100)}%"
    if notice:
        line += f"  {notice}"
    return line


def _compute_inspect_layout(
    image_area: ArtifactFileImageArea,
    *,
    storyboard_enabled: bool,
    pane_rows: int | None = None,
) -> _VideoInspectLayout:
    """Split *image_area* into a frame region and optional storyboard strip."""

    visual_rows = max(_MIN_IMAGE_ROWS, image_area.rows)
    columns = max(1, image_area.columns)
    left = max(0, image_area.left)
    top = max(0, image_area.top)
    total_rows = pane_rows if pane_rows is not None else top + visual_rows + 2
    show = bool(storyboard_enabled and total_rows >= _STORYBOARD_MIN_PANE_ROWS)
    storyboard_rows = 0
    if show:
        storyboard_rows = max(_STORYBOARD_MIN_ROWS, visual_rows // 3)
        frame_rows = visual_rows - storyboard_rows
        if frame_rows < _MIN_IMAGE_ROWS:
            frame_rows = _MIN_IMAGE_ROWS
            storyboard_rows = visual_rows - frame_rows
        if storyboard_rows < _STORYBOARD_MIN_ROWS:
            show = False
            storyboard_rows = 0
            frame_rows = visual_rows
    else:
        frame_rows = visual_rows
    frame = ArtifactFileImageArea(
        columns=columns, rows=max(_MIN_IMAGE_ROWS, frame_rows), left=left, top=top
    )
    storyboard = None
    if show:
        storyboard = ArtifactFileImageArea(
            columns=columns,
            rows=storyboard_rows,
            left=left,
            top=top + frame.rows,
        )
    status_row = max(1, top + visual_rows)
    return _VideoInspectLayout(
        frame=frame,
        storyboard=storyboard,
        status_row=status_row,
        footer_row=status_row + 1,
        columns=columns,
        pane_rows=total_rows,
        show_storyboard=show,
    )


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
) -> _VideoInspectOutcome:
    """Run the inspect-first video view until a sequence-loop outcome."""

    _ = cache_root
    session = _InspectSession(
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


class _KeySource:
    """Pushback buffer so coalescing can unread a non-step key."""

    def __init__(self, read: ReadKey) -> None:
        self._read = read
        self._unread: list[str | None] = []

    def get(self, timeout: float | None = None) -> str | None:
        if self._unread:
            return self._unread.pop()
        try:
            return self._read(timeout=timeout)
        except TypeError:
            return self._read()

    def unread(self, key: str | None) -> None:
        self._unread.append(key)


class _InspectSession:
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
        self._read = read_key or _read_inspect_key
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

    def run(self) -> _VideoInspectOutcome:
        if not self.path.exists():
            warning = ArtifactFileViewerWarning(
                "artifact_not_found", "Artifact file not found"
            )
            return _VideoInspectOutcome(
                action="quit", returncode=1, warnings=(warning,)
            )
        if not self.path.is_file():
            warning = ArtifactFileViewerWarning(
                "artifact_not_file", "Artifact path is not a file"
            )
            return _VideoInspectOutcome(
                action="quit", returncode=1, warnings=(warning,)
            )
        self._prepare()
        self._paint(full=True)
        self._start_background()
        self._poll_background()
        keys = _KeySource(self._read)
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

    def _prepare(self) -> None:
        if content_digest_for_path(self.path) is None:
            self.notice = "could not read video file"
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

    def _compute_layout(self) -> _VideoInspectLayout:
        if self._fixed_area is not None:
            area = self._fixed_area
            pane_rows = area.top + area.rows + 2
        else:
            area = artifact_image_area(self._term_size)
            pane_rows = int(self._term_size.lines)
        return _compute_inspect_layout(
            area, storyboard_enabled=self.storyboard_enabled, pane_rows=pane_rows
        )

    def _frame_max_px(self) -> int:
        pixel_width, _ = terminal_pixel_size()
        columns = max(1, self.layout.columns)
        return max(1, int(pixel_width * self.layout.frame.columns / columns))

    def _paint(self, *, full: bool) -> None:
        if full:
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
            self._icat(result.path, self.layout.frame, _FRAME_IMAGE_ID)
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

    def _frame_at(self, at_seconds: float, *, exact: bool) -> FrameExtractResult:
        if not exact and self.scrub is not None:
            nearest = self.scrub.nearest(at_seconds)
            if nearest is not None:
                return FrameExtractResult(path=nearest, cached=True, error=None)
        return extract_frame(
            self.path, at_seconds, self._frame_max_px(), cache_dir=self.cache
        )

    def _icat(self, page: Path, area: ArtifactFileImageArea, image_id: int) -> None:
        if shutil.which("kitten") is None:
            self.notice = "kitten executable not found: video frame cannot display"
            return
        command = viewer_kitten_icat_command(page, area, image_id=image_id)
        result = self._run(command)
        if getattr(result, "returncode", 0) != 0:
            self.notice = (
                f"kitten icat failed with exit code {getattr(result, 'returncode', 1)}"
            )

    def _print_status(self) -> None:
        progress = None if self.scrub is None else self.scrub.progress
        text = _format_inspect_status(
            self.at, self.duration, scrub_progress=progress, notice=self.notice
        )
        line = text[: self.layout.columns].ljust(self.layout.columns)
        sys.stdout.write(f"\x1b[{self.layout.status_row};1H{line}")
        sys.stdout.flush()

    def _print_footer(self) -> None:
        parts = [
            "h/l: seek",
            ",/.: frame",
            "0-9: jump",
            "s: board",
            "space: play",
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

    def _coalesce(self, keys: _KeySource, first: str) -> list[str]:
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
                self.at = _step_timestamp(self.at, 1.0, self.duration)
                snap = True
            elif key in _STEP_BACK:
                self.at = _step_timestamp(self.at, -1.0, self.duration)
                snap = True
            elif key in _FRAME_FORWARD:
                self.at = _step_timestamp(self.at, 1.0 / self.source_fps, self.duration)
                exact = True
            elif key in _FRAME_BACK:
                self.at = _step_timestamp(
                    self.at, -1.0 / self.source_fps, self.duration
                )
                exact = True
        if snap and not exact:
            self.at = _clamp_timestamp(
                _snap_timestamp(self.at, self.scrub), self.duration
            )
        self._want_exact = exact

    def _handle_key(self, key: str) -> _VideoInspectOutcome | None:
        if key == "q":
            clear_terminal()
            return _VideoInspectOutcome()
        if key == _RETURN_TO_ACE_KEY and self.return_pane_id:
            if self._select is not None:
                selected = self._select(self.return_pane_id)
                if not selected.ok:
                    return _VideoInspectOutcome(
                        action="quit",
                        returncode=1,
                        warnings=selected.warnings,
                    )
            return None
        if key == "n" and self.artifact_index < self.artifact_count - 1:
            return _VideoInspectOutcome(action="next")
        if key == "p" and self.artifact_index > 0:
            return _VideoInspectOutcome(action="previous")
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
                return _VideoInspectOutcome(
                    action="quit", returncode=1, warnings=zoomed.warnings
                )
            self.layout = self._compute_layout()
            self._restart_storyboard()
            self._paint(full=True)
            return None
        if key == " ":
            self._play_motion()
            return None
        if len(key) == 1 and key.isdigit():
            self.at = _decile_timestamp(int(key), self.duration)
            self._print_status()
            self._render_frame(span=True)
            return None
        return None

    def _play_motion(self) -> None:
        if (
            video_still_preview_required(self.video_config)
            or shutil.which("mpv") is None
        ):
            self.notice = _MOTION_UNAVAILABLE
            self._print_status()
            return
        command = artifact_video_player_command(
            self.path, self.layout.frame, self.video_config
        )
        result = self._run(command)
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

    def _restart_storyboard(self) -> None:
        self._storyboard_shown = False
        self._storyboard_result = None
        self._start_storyboard()


__all__ = [
    "run_video_inspect",
]

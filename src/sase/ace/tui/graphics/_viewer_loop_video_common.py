"""Shared inspect helpers for the terminal video viewer.

Pure key-decoding, timestamp math, and inspect-layout helpers used by the
video inspect session. Public names here are the cross-module seam; in-file
only helpers stay private.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import Any

from ._viewer_loop_terminal import _MIN_IMAGE_ROWS
from ._viewer_types import ArtifactFileImageArea
from ._viewer_video_frames import ScrubTrack
from ._viewer_video_input import read_inspect_key

ReadKey = Callable[..., str | None]
RunCommand = Callable[[Sequence[str]], CompletedProcess[Any]]
SelectPane = Callable[[str], Any]
ToggleZoom = Callable[[], Any]

_STORYBOARD_MIN_ROWS = 5
_STORYBOARD_MIN_PANE_ROWS = 20


@dataclass(frozen=True)
class VideoInspectLayout:
    """Cell geometry for the inspect frame, storyboard, status, and footer."""

    frame: ArtifactFileImageArea
    storyboard: ArtifactFileImageArea | None
    status_row: int
    footer_row: int
    columns: int
    pane_rows: int
    show_storyboard: bool


def clamp_timestamp(at_seconds: float, duration_seconds: float | None) -> float:
    """Clamp *at_seconds* into ``[0, duration]``, or ``[0, inf)`` when unknown."""

    at = max(0.0, float(at_seconds))
    if duration_seconds is not None and duration_seconds >= 0:
        at = min(at, duration_seconds)
    return at


def decile_timestamp(digit: int, duration_seconds: float | None) -> float:
    """Return the timestamp for jump key ``0``–``9``."""

    if duration_seconds is None or duration_seconds <= 0:
        return 0.0
    return clamp_timestamp(digit * duration_seconds / 10.0, duration_seconds)


def snap_timestamp(at_seconds: float, scrub: ScrubTrack | None) -> float:
    """Snap *at_seconds* onto a completed scrub track, else leave it exact."""

    if scrub is None or not scrub.done or scrub.fps <= 0:
        return at_seconds
    frames = scrub.frame_paths
    if not frames:
        return at_seconds
    index = int(round(at_seconds * scrub.fps))
    index = max(0, min(index, len(frames) - 1))
    return index / scrub.fps


def step_timestamp(
    at_seconds: float,
    delta_seconds: float,
    duration_seconds: float | None,
    *,
    scrub: ScrubTrack | None = None,
    snap: bool = False,
) -> float:
    """Apply a seek delta and optionally snap onto the scrub track."""

    target = clamp_timestamp(at_seconds + delta_seconds, duration_seconds)
    if snap:
        return clamp_timestamp(snap_timestamp(target, scrub), duration_seconds)
    return target


def _format_inspect_timestamp(at_seconds: float) -> str:
    """Format a playhead as ``mm:ss.d``."""

    total = max(0.0, float(at_seconds))
    minutes = int(total // 60)
    seconds = total - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def format_inspect_status(
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


def compute_inspect_layout(
    image_area: ArtifactFileImageArea,
    *,
    storyboard_enabled: bool,
    pane_rows: int | None = None,
) -> VideoInspectLayout:
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
    return VideoInspectLayout(
        frame=frame,
        storyboard=storyboard,
        status_row=status_row,
        footer_row=status_row + 1,
        columns=columns,
        pane_rows=total_rows,
        show_storyboard=show,
    )


class KeySource:
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


__all__ = [
    "KeySource",
    "ReadKey",
    "RunCommand",
    "SelectPane",
    "ToggleZoom",
    "VideoInspectLayout",
    "clamp_timestamp",
    "compute_inspect_layout",
    "decile_timestamp",
    "format_inspect_status",
    "read_inspect_key",
    "snap_timestamp",
    "step_timestamp",
]

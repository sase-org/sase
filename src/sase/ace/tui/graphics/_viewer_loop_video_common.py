"""Shared inspect helpers for the terminal video viewer.

Pure key-decoding, timestamp math, and inspect-layout helpers used by the
video inspect session. Public names here are the cross-module seam; in-file
only helpers stay private.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import Any

from ._viewer_loop_terminal import _MIN_IMAGE_ROWS
from ._viewer_types import ArtifactFileImageArea
from ._viewer_video_frames import ScrubTrack

ReadKey = Callable[..., str | None]
RunCommand = Callable[[Sequence[str]], CompletedProcess[Any]]
SelectPane = Callable[[str], Any]
ToggleZoom = Callable[[], Any]

_ARROW_KEY_SEQUENCES = {
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1bOC": "right",
    "\x1bOD": "left",
}
_INSPECT_ESC_TIMEOUT_SECONDS = 0.03
_STORYBOARD_MIN_ROWS = 5
_STORYBOARD_MIN_PANE_ROWS = 20


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


def read_inspect_key(*, timeout: float | None = 0.05) -> str | None:
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

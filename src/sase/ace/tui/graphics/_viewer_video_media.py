"""ffprobe metadata for terminal video artifacts."""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import termios
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from struct import pack, unpack
from sys import stdout
from typing import Any

from ._viewer_loop_media import (
    video_still_preview_required,
    video_vo_uses_kitty_placement,
)

_FFPROBE_TIMEOUT_SECONDS = 5.0
_FALLBACK_TERMINAL_PIXEL_WIDTH = 1600
_FALLBACK_TERMINAL_PIXEL_HEIGHT = 900


@dataclass(frozen=True)
class VideoMetadata:
    """Optional ffprobe metadata for a terminal video artifact."""

    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    size_bytes: int | None = None


def ffprobe_metadata_command(path: str | Path) -> list[str]:
    """Build the ffprobe command that reports video metadata as JSON."""

    expanded = Path(path).expanduser().resolve(strict=False)
    return [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "v:0",
        str(expanded),
    ]


def parse_ffprobe_metadata(
    payload: dict[str, Any],
    *,
    file_size: int | None = None,
) -> VideoMetadata:
    """Parse ffprobe JSON output into optional video metadata fields."""

    streams = payload.get("streams")
    stream: dict[str, Any] | None = None
    if isinstance(streams, list):
        for candidate in streams:
            if not isinstance(candidate, dict):
                continue
            if stream is None:
                stream = candidate
            if candidate.get("codec_type") == "video":
                stream = candidate
                break
    stream = stream or {}
    container = payload.get("format")
    if not isinstance(container, dict):
        container = {}

    return VideoMetadata(
        duration_seconds=_parse_float(container.get("duration")),
        width=_parse_int(stream.get("width")),
        height=_parse_int(stream.get("height")),
        fps=_parse_frame_rate(stream.get("avg_frame_rate"))
        or _parse_frame_rate(stream.get("r_frame_rate")),
        codec=_parse_str(stream.get("codec_name")),
        size_bytes=_parse_int(container.get("size"), fallback=file_size),
    )


def format_video_metadata_summary(metadata: VideoMetadata) -> str | None:
    """Format optional metadata as a ``·``-separated media label summary."""

    parts: list[str] = []
    if metadata.duration_seconds is not None:
        parts.append(_format_duration(metadata.duration_seconds))
    if metadata.width is not None and metadata.height is not None:
        parts.append(f"{metadata.width}\u00d7{metadata.height}")
    if metadata.fps is not None:
        parts.append(f"{int(round(metadata.fps))} fps")
    if metadata.codec:
        parts.append(metadata.codec)
    if metadata.size_bytes is not None:
        parts.append(_format_bytes(metadata.size_bytes))
    if not parts:
        return None
    return " \u00b7 ".join(parts)


def terminal_pixel_size(
    *,
    fallback_width: int = _FALLBACK_TERMINAL_PIXEL_WIDTH,
    fallback_height: int = _FALLBACK_TERMINAL_PIXEL_HEIGHT,
) -> tuple[int, int]:
    """Return the terminal pixel size from ``TIOCGWINSZ``, or the fallbacks."""

    try:
        _, _, xpixels, ypixels = unpack(
            "HHHH",
            fcntl.ioctl(stdout.fileno(), termios.TIOCGWINSZ, pack("HHHH", 0, 0, 0, 0)),
        )
    except (OSError, ValueError):
        return (fallback_width, fallback_height)
    width = xpixels if xpixels > 0 else fallback_width
    height = ypixels if ypixels > 0 else fallback_height
    return (width, height)


def probe_video_metadata(path: str | Path) -> VideoMetadata | None:
    """Probe *path* with ffprobe, returning ``None`` when unavailable."""

    if shutil.which("ffprobe") is None:
        return None
    expanded = Path(path).expanduser().resolve(strict=False)
    try:
        file_size = expanded.stat().st_size if expanded.is_file() else None
    except OSError:
        file_size = None
    result = _run_capture(ffprobe_metadata_command(expanded), _FFPROBE_TIMEOUT_SECONDS)
    if result is None or result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return parse_ffprobe_metadata(payload, file_size=file_size)


def _run_capture(
    command: Sequence[str],
    timeout: float,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _parse_float(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed


def _parse_int(value: object, *, fallback: int | None = None) -> int | None:
    if value is None:
        return fallback
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def _parse_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _parse_frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or not value or value in {"0/0"}:
        return None
    numerator, separator, denominator = value.partition("/")
    try:
        if separator:
            parsed = float(numerator) / float(denominator)
        else:
            parsed = float(numerator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return parsed if parsed > 0 else None


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _format_bytes(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    if size < 1_000_000:
        return f"{size / 1000:.0f} KB"
    if size < 1_000_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000_000_000:.1f} GB"


__all__ = [
    "VideoMetadata",
    "ffprobe_metadata_command",
    "format_video_metadata_summary",
    "parse_ffprobe_metadata",
    "probe_video_metadata",
    "terminal_pixel_size",
    "video_still_preview_required",
    "video_vo_uses_kitty_placement",
]

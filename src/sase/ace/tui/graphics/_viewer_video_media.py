"""ffprobe metadata and single-still extraction for terminal video artifacts."""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import tempfile
import termios
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from struct import pack, unpack
from sys import stdout
from typing import Any

from ._viewer_loop_media import (
    video_still_preview_required,
    video_vo_uses_kitty_placement,
)
from ._viewer_loop_terminal import (
    clear_terminal,
    kitten_icat_command,
    move_cursor_below_image,
    print_artifact_header,
    print_artifact_warning,
)
from ._viewer_loop_types import VideoDisplayResult
from ._viewer_types import (
    ArtifactFileImageArea,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
)

_FFPROBE_TIMEOUT_SECONDS = 5.0
_FFMPEG_TIMEOUT_SECONDS = 10.0
_FALLBACK_TERMINAL_PIXEL_WIDTH = 1600

VIDEO_STILL_FOOTER_PREFIX = (
    "still frame \u00b7 in-pane playback is unavailable inside tmux"
)


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


def _video_still_extraction_command(
    path: str | Path,
    dest: str | Path,
    max_pixel_width: int,
) -> list[str]:
    """Build the ffmpeg command that extracts the first frame as a PNG still."""

    expanded = Path(path).expanduser().resolve(strict=False)
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        "0",
        "-i",
        str(expanded),
        "-frames:v",
        "1",
        "-vf",
        f"scale=min(iw\\,{max_pixel_width}):-2",
        str(Path(dest).expanduser()),
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


def _terminal_pixel_width(
    *,
    fallback: int = _FALLBACK_TERMINAL_PIXEL_WIDTH,
) -> int:
    """Return the terminal pixel width from ``TIOCGWINSZ``, or *fallback*."""

    try:
        _, _, xpixels, _ = unpack(
            "HHHH",
            fcntl.ioctl(stdout.fileno(), termios.TIOCGWINSZ, pack("HHHH", 0, 0, 0, 0)),
        )
    except (OSError, ValueError):
        return fallback
    return xpixels if xpixels > 0 else fallback


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


def _extract_video_still(
    path: str | Path,
    dest: str | Path,
    max_pixel_width: int | None = None,
) -> bool:
    """Extract the first frame of *path* into *dest*, downscaling as needed."""

    if shutil.which("ffmpeg") is None:
        return False
    width = max_pixel_width if max_pixel_width and max_pixel_width > 0 else None
    resolved_width = width or _terminal_pixel_width()
    output = Path(dest).expanduser()
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    result = _run_capture(
        _video_still_extraction_command(path, output, resolved_width),
        _FFMPEG_TIMEOUT_SECONDS,
    )
    if result is None or result.returncode != 0:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def display_video_still_artifact(
    spec: ArtifactFileViewSpec,
    image_area: ArtifactFileImageArea,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
    *,
    cache_root: str | Path | None = None,
    artifact_index: int = 0,
    artifact_count: int = 1,
) -> VideoDisplayResult:
    """Render a video as an ffmpeg still plus ffprobe metadata, never mpv.

    Every missing or failed tool prints a yellow notice naming the tool and
    keeps the viewer alive: the result carries notices instead of warnings so
    the sequence loop never exits on this path.
    """

    path = Path(spec.path).expanduser().resolve(strict=False)
    notices: list[ArtifactFileViewerWarning] = []
    metadata: VideoMetadata | None = None
    if shutil.which("ffprobe") is None:
        notices.append(
            ArtifactFileViewerWarning(
                "missing_ffprobe",
                "ffprobe executable not found: video metadata unavailable",
                tool="ffprobe",
            )
        )
    else:
        metadata = probe_video_metadata(path)
        if metadata is None:
            notices.append(
                ArtifactFileViewerWarning(
                    "ffprobe_failed",
                    "ffprobe could not read video metadata",
                    tool="ffprobe",
                )
            )

    summary = format_video_metadata_summary(metadata) if metadata else None
    media_label = f"\u25b6 Video {summary}" if summary else "\u25b6 Video"

    still_path: Path | None = None
    if shutil.which("ffmpeg") is None:
        notices.append(
            ArtifactFileViewerWarning(
                "missing_ffmpeg",
                "ffmpeg executable not found: video still unavailable",
                tool="ffmpeg",
            )
        )
    else:
        root = (
            Path(cache_root).expanduser()
            if cache_root is not None
            else Path(tempfile.mkdtemp(prefix="sase-video-still-"))
        )
        still_path = root / f"video-still-{artifact_index}.png"
        if not _extract_video_still(path, still_path):
            notices.append(
                ArtifactFileViewerWarning(
                    "ffmpeg_still_failed",
                    "ffmpeg could not extract a video still frame",
                    tool="ffmpeg",
                )
            )
            still_path = None

    clear_terminal()
    print_artifact_header(
        spec,
        page_index=0,
        page_count=1,
        artifact_index=artifact_index,
        artifact_count=artifact_count,
        media_label=media_label,
    )
    command: tuple[str, ...] = ()
    if still_path is not None:
        if shutil.which("kitten") is None:
            notices.append(
                ArtifactFileViewerWarning(
                    "missing_kitten",
                    "kitten executable not found: video still cannot display",
                    tool="kitten",
                )
            )
        else:
            icat_command = kitten_icat_command(still_path, image_area)
            result = run_command(icat_command)
            command = tuple(icat_command)
            if result.returncode != 0:
                command = ()
                notices.append(
                    ArtifactFileViewerWarning(
                        "kitten_icat_failed",
                        f"kitten icat failed with exit code {result.returncode}",
                        tool="kitten",
                    )
                )
    move_cursor_below_image(image_area)
    for notice in notices:
        print_artifact_warning(notice)
    return VideoDisplayResult(
        command=command,
        returncode=0,
        notices=tuple(notices),
        still_preview=True,
    )


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
    "VIDEO_STILL_FOOTER_PREFIX",
    "VideoMetadata",
    "display_video_still_artifact",
    "ffprobe_metadata_command",
    "format_video_metadata_summary",
    "parse_ffprobe_metadata",
    "probe_video_metadata",
    "video_still_preview_required",
    "video_vo_uses_kitty_placement",
]

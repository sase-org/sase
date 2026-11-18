"""Video preview helpers for prompt readers in sase's TUI."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from rich.console import RenderableType

from ._video_preview_types import VIDEO_PREVIEW_FRAME_PX, VideoPreviewInfo
from .capability import ImageRenderContext, image_render_context
from .renderable import ImageFallbackRenderable, image_preview
from ._viewer_loop_video_common import decile_timestamp, format_inspect_status
from ._viewer_video_frames import (
    VideoMetadata,
    artifact_video_cache_dir,
    extract_frame,
    metadata_for_frame_service,
)
from ._viewer_video_media import format_video_metadata_summary

_VIDEO_FALLBACK_HINT = "Press Z to open it in the artifact viewer"


def load_video_preview_info(
    path: str | Path,
    *,
    cache_dir: str | Path | None = None,
) -> VideoPreviewInfo:
    """Probe video metadata using the artifact viewer's digest-keyed cache."""
    try:
        expanded = Path(path).expanduser()
        try:
            file_size = expanded.stat().st_size if expanded.is_file() else None
        except OSError:
            file_size = None

        metadata = metadata_for_frame_service(
            path,
            cache_dir=artifact_video_cache_dir(cache_dir=cache_dir),
        )
        notice = None
        if metadata is None:
            if shutil.which("ffprobe") is None:
                notice = "ffprobe not found: video metadata unavailable"
            else:
                notice = "ffprobe could not read video metadata"
            metadata = (
                VideoMetadata(size_bytes=file_size) if file_size is not None else None
            )
        elif metadata.size_bytes is None and file_size is not None:
            metadata = replace(metadata, size_bytes=file_size)

        return VideoPreviewInfo(
            metadata=metadata,
            summary=(
                format_video_metadata_summary(metadata)
                if metadata is not None
                else None
            ),
            duration_seconds=(
                metadata.duration_seconds if metadata is not None else None
            ),
            notice=notice,
        )
    except Exception as exc:
        try:
            file_size = Path(path).expanduser().stat().st_size
            metadata = VideoMetadata(size_bytes=file_size)
        except OSError:
            metadata = None
        return VideoPreviewInfo(
            metadata=metadata,
            summary=(
                format_video_metadata_summary(metadata)
                if metadata is not None
                else None
            ),
            duration_seconds=None,
            notice=f"Video metadata unavailable: {exc}",
        )


def video_preview_frame(
    path: str | Path,
    at_seconds: float,
    context: ImageRenderContext | None = None,
    *,
    columns: int,
    rows: int,
    cache_dir: str | Path | None = None,
) -> RenderableType:
    """Extract one cached video frame and render it at the requested cell size."""
    expanded = str(Path(path).expanduser())
    name = Path(expanded).name
    try:
        result = extract_frame(
            expanded,
            at_seconds,
            VIDEO_PREVIEW_FRAME_PX,
            cache_dir=cache_dir,
        )
        if result.ok and result.path is not None:
            try:
                render_context = context or image_render_context()
                return image_preview(
                    str(result.path),
                    render_context,
                    columns=columns,
                    rows=rows,
                    fallback_hint=_VIDEO_FALLBACK_HINT,
                )
            except Exception as exc:
                reason = f"video frame render failed: {exc}"
        else:
            reason = result.error or "video frame extraction failed"
    except Exception as exc:
        reason = f"video frame extraction failed: {exc}"

    return ImageFallbackRenderable(
        expanded,
        reason,
        _VIDEO_FALLBACK_HINT,
        heading="▶ video preview unavailable",
        name=name,
    )


def video_preview_timestamp(decile: int, duration_seconds: float | None) -> float:
    """Return a preview decile timestamp using the artifact viewer's seek math."""
    return decile_timestamp(decile, duration_seconds)


def format_video_preview_position(
    decile: int,
    duration_seconds: float | None,
) -> str:
    """Format the current decile and playhead using the artifact viewer status line."""
    at_seconds = video_preview_timestamp(decile, duration_seconds)
    return (
        f"frame {decile + 1}/10 · {format_inspect_status(at_seconds, duration_seconds)}"
    )


__all__ = [
    "VIDEO_PREVIEW_FRAME_PX",
    "VideoPreviewInfo",
    "format_video_preview_position",
    "load_video_preview_info",
    "video_preview_frame",
    "video_preview_timestamp",
]

"""Lightweight types shared by the lazy video preview seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._viewer_video_media import VideoMetadata

VIDEO_PREVIEW_FRAME_PX = 640


@dataclass(frozen=True)
class VideoPreviewInfo:
    """Cached video metadata and any optional-tool notice for a prompt preview."""

    metadata: VideoMetadata | None
    summary: str | None
    duration_seconds: float | None
    notice: str | None = None


__all__ = ["VIDEO_PREVIEW_FRAME_PX", "VideoPreviewInfo"]

"""Facade for ffmpeg-backed frame services used by video artifacts.

The implementation is split by responsibility; public imports remain available here.
"""

from __future__ import annotations

from ._viewer_video_cache import (
    artifact_video_cache_dir,
    content_digest_for_path,
    enforce_cache_budget,
    metadata_for_frame_service,
)
from ._viewer_video_extract import FrameExtractResult, extract_frame
from ._viewer_video_media import (
    VideoMetadata,
    ffprobe_metadata_command,
    parse_ffprobe_metadata,
    probe_video_metadata,
)
from ._viewer_video_scrub import ScrubTrack, scrub_fps_for_duration, start_scrub_track
from ._viewer_video_storyboard import StoryboardResult, build_storyboard

__all__ = [
    "FrameExtractResult",
    "ScrubTrack",
    "StoryboardResult",
    "artifact_video_cache_dir",
    "build_storyboard",
    "content_digest_for_path",
    "enforce_cache_budget",
    "extract_frame",
    "metadata_for_frame_service",
    "scrub_fps_for_duration",
    "start_scrub_track",
]

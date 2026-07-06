"""Shared media suffix helpers."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov", ".webm"})


def is_supported_video_path(path: str | Path) -> bool:
    """Return whether *path* has a video extension supported by SASE."""
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS

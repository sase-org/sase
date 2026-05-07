"""Image path helpers for TUI preview surfaces."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def is_supported_image_path(path: str | Path) -> bool:
    """Return whether *path* has an image extension supported by SASE previews."""
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS

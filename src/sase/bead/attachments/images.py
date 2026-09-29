"""Bounded image probing for attachment descriptors.

``probe_image`` opens with Pillow headers only (no full decode), applies the
same caps the cell renderer uses, and never raises: anything undecodable —
including SVG, which is classified but never decoded — yields ``None``.
Pillow is imported lazily so beads without attachments never pay for it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImageDims:
    """Probed pixel dimensions of an image attachment."""

    width: int
    height: int


_SVG_SUFFIXES = {".svg", ".svgz"}


def probe_image(path: str | os.PathLike[str]) -> ImageDims | None:
    """Return the pixel dimensions of *path*, or None when not previewable."""
    suffix = Path(path).suffix.lower()
    if suffix in _SVG_SUFFIXES:
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    try:
        from sase.ace.tui.graphics.cell import (
            MAX_CELL_IMAGE_FILE_BYTES,
            MAX_CELL_IMAGE_PIXELS,
        )
    except ImportError:  # pragma: no cover - missing optional dep
        return None
    if size > MAX_CELL_IMAGE_FILE_BYTES:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
    except Exception:
        return None
    if width <= 0 or height <= 0 or width * height > MAX_CELL_IMAGE_PIXELS:
        return None
    return ImageDims(width=width, height=height)

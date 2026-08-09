"""ProjectSpec Patch storage spelling helpers."""

from __future__ import annotations

import re

CANONICAL_PATCH_HEADING = "## Patch"
LEGACY_PATCH_HEADING = "## ChangeSpec"
DEFAULT_STITCH_SECTION_HEADER = "STITCHES:"
LEGACY_STITCH_SECTION_HEADER = "COMMITS:"
STITCH_SECTION_HEADERS = (
    DEFAULT_STITCH_SECTION_HEADER,
    LEGACY_STITCH_SECTION_HEADER,
)

_PATCH_HEADING_RE = re.compile(
    r"^##\s+(?:Patch|ChangeSpec)\b"
)  # legacy compatibility alias


def is_patch_heading(line: str) -> bool:
    """Return True when *line* starts a canonical or legacy Patch record."""
    return bool(_PATCH_HEADING_RE.match(line.strip()))


def is_stitch_section_header(line: str) -> bool:
    """Return True for canonical or legacy stitch-history section headers."""
    return line.startswith(STITCH_SECTION_HEADERS)


def stitch_section_header_for(line: str) -> str | None:
    """Return the normalized stitch-history header from *line*, if present."""
    stripped = line.strip()
    if stripped in STITCH_SECTION_HEADERS:
        return stripped
    return None


__all__ = [
    "CANONICAL_PATCH_HEADING",
    "DEFAULT_STITCH_SECTION_HEADER",
    "LEGACY_PATCH_HEADING",
    "LEGACY_STITCH_SECTION_HEADER",
    "STITCH_SECTION_HEADERS",
    "is_patch_heading",
    "is_stitch_section_header",
    "stitch_section_header_for",
]

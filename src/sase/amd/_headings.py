"""Fence-aware Markdown heading primitives for AMD documents."""

from __future__ import annotations

import re

_FENCE_MARKERS = ("```", "~~~")
_HEADING_RE = re.compile(r"^(#+)(?:[ \t]|$)")


def fence_marker(line: str) -> str | None:
    """Return the fence marker (``` ``` ``` or ``~~~``) opening/closing *line*."""
    stripped = line.lstrip()
    for marker in _FENCE_MARKERS:
        if stripped.startswith(marker):
            return marker
    return None


def heading_level(line: str) -> int | None:
    """Return the ATX heading level of *line*, or ``None`` if it is not one.

    Headings are recognized only at column zero (matching how canonical memory
    notes are authored) and must be followed by whitespace or end-of-line.
    """
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    return len(match.group(1))


def iter_headings(body: str) -> list[tuple[int, str]]:
    """Return ``(level, line)`` for every heading outside fenced code blocks."""
    headings: list[tuple[int, str]] = []
    in_fence = False
    active_fence_marker = ""
    for line in body.splitlines():
        marker = fence_marker(line)
        if in_fence:
            if marker == active_fence_marker:
                in_fence = False
            continue
        if marker is not None:
            in_fence = True
            active_fence_marker = marker
            continue
        level = heading_level(line)
        if level is not None:
            headings.append((level, line))
    return headings


__all__ = [
    "fence_marker",
    "heading_level",
    "iter_headings",
]

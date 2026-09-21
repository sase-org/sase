"""Shared display helpers for the timeline renderers."""

from __future__ import annotations

from .events import StepStatus

STATUS_GLYPH: dict[StepStatus, str] = {
    "pending": "○",
    "running": "⠋",
    "done": "✓",
    "warned": "⚠",
    "failed": "✗",
    "skipped": "–",
    "interrupted": "■",
}
"""Glyph per step status. Glyphs back words, never replace them."""

FINAL_GLYPH: dict[StepStatus, str] = {
    **STATUS_GLYPH,
    "running": "●",
    "pending": "○",
}
"""Static glyphs for the final frame (no spinner)."""

STATUS_STYLE: dict[StepStatus, str] = {
    "pending": "dim",
    "running": "cyan",
    "done": "green",
    "warned": "yellow",
    "failed": "red",
    "skipped": "dim",
    "interrupted": "red",
}
"""Color per step status. Color adds meaning but is never load-bearing."""


def format_duration(seconds: float) -> str:
    """Format a step duration: ``0.4s`` below a minute, ``1:02`` above."""
    seconds = max(0.0, seconds)
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_span(seconds: float) -> str:
    """Format an overall elapsed clock: ``0:44`` style, ``1:02:03`` past an hour."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_stamp(seconds: float) -> str:
    """Format a plain-mode ``[mm:ss]`` elapsed stamp."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"

"""Shared language color identity for the Projects language breakdown."""

from __future__ import annotations

from sase.stats.render._text import UNKNOWN_STYLE

_LANGUAGE_COLORS: dict[str, str] = {
    "python": "#3987e5",
    "rust": "#d95926",
    "typescript": "#199e70",
    "tsx": "#199e70",
    "javascript": "#c98500",
    "jsx": "#c98500",
    "lua": "#d55181",
    "sh": "#008300",
    "bash": "#008300",
    "zsh": "#008300",
    "fish": "#008300",
    "css": "#9085e9",
    "scss": "#9085e9",
    "sass": "#9085e9",
    "less": "#9085e9",
    "html": "#e66767",
}

NEUTRAL_COLOR = "#8a8984"

# Every new slot must be re-validated with the dataviz validator against the
# TUI Statistics surface (#1c1b1a) for lightness, chroma, CVD distance, and
# contrast before landing.


def language_color(language_id: str | None) -> str:
    """Return the identity color for a language id (neutral fallback)."""
    if language_id is None:
        return UNKNOWN_STYLE
    return _LANGUAGE_COLORS.get(language_id, NEUTRAL_COLOR)


__all__ = [
    "language_color",
    "NEUTRAL_COLOR",
]

"""Shared primitives for ``sase plugin`` Rich renderers."""

from __future__ import annotations

#: Glyphs (never color alone) for installed vs. available plugins.
_INSTALLED_GLYPH = "●"
_AVAILABLE_GLYPH = "○"
_UPDATE_GLYPH = "↑"

#: Glyphs (never color alone) for the ``show`` installed/not-installed row.
_INSTALLED_CHECK = "✓"
_NOT_INSTALLED_CROSS = "✗"

#: Result glyphs (never color alone), mirroring the ``sase update`` renderer.
_CHANGED_GLYPH = "✓"
_UNCHANGED_GLYPH = "·"

#: Placeholder for an empty cell (em dash).
_EMPTY = "—"

_BUILTIN_STYLE = "green"
_COMMUNITY_STYLE = "yellow"

_REFRESH_COMMAND = "`sase plugin list --refresh`"


def humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m{rest:02d}s"


def humanize_age(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    return f"{days}d ago"

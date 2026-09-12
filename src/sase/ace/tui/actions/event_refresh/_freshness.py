"""In-memory refresh freshness stamps for ACE surfaces."""

from __future__ import annotations

import time
from typing import Any

RECORDED_SURFACES = (
    "agents",
    "agents_full_history",
    "patches",
    "artifacts",
    "axe",
    "notifications",
)
_RECORDED_SURFACE_SET = frozenset(RECORDED_SURFACES)


def note_surface_refreshed(
    app: Any,
    surface: str,
    *,
    now: float | None = None,
) -> None:
    """Record that *surface* was requested or reloaded in this session."""
    if surface not in _RECORDED_SURFACE_SET:
        return
    stamps = getattr(app, "_surface_refreshed_mono", None)
    if stamps is None:
        stamps = {}
        app._surface_refreshed_mono = stamps
    stamps[surface] = time.monotonic() if now is None else now


def surface_refreshed_age(app: Any, surface: str) -> float | None:
    """Return seconds since *surface* was refreshed, if it has a session stamp."""
    stamps = getattr(app, "_surface_refreshed_mono", None)
    if not isinstance(stamps, dict):
        return None
    refreshed_at = stamps.get(surface)
    if refreshed_at is None:
        return None
    return max(0.0, time.monotonic() - float(refreshed_at))


def freshness_label(age: float | None) -> str:
    """Format a supplied freshness age for the refresh panel."""
    if age is None:
        return "—"
    if age < 5:
        return "just now"
    seconds = int(age)
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"

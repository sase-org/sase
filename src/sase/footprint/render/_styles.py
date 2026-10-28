"""Shared visual language for Footprint reports."""

from __future__ import annotations

# Statistics accent ramp means recency, and only recency.
RECENT_7D_GLYPH = "█"
RECENT_7D_STYLE = "#FF87D7"
RECENT_30D_GLYPH = "▓"
RECENT_30D_STYLE = "#B46A9C"
RECENT_WINDOW_GLYPH = "▒"
RECENT_WINDOW_STYLE = "#6E5A6B"

# A zero is neutral, never red.
ZERO_GLYPH = "·"
ZERO_STYLE = "#808080"

# Not measured always carries a text label, never a pale zero.
NOT_MEASURED_GLYPH = "?"
NOT_MEASURED_STYLE = "#87D7FF"

# Amber marks preview or incomplete evidence; red is collector faults only.
PREVIEW_STYLE = "#FFD700"
FAULT_STYLE = "#FF5F5F"
MUTED_STYLE = "dim"

# Cold marker below 25% used.
COLD_MARKER = "◂"

STATE_GLYPHS: dict[str, tuple[str, str]] = {
    "used": ("●", "green"),
    "no_recorded_use": ("○", NOT_MEASURED_STYLE),
    "rare_by_design": ("◈", MUTED_STYLE),
    "too_new": ("◐", PREVIEW_STYLE),
    "not_measured": (NOT_MEASURED_GLYPH, NOT_MEASURED_STYLE),
    "retired": ("–", MUTED_STYLE),
}

STATE_LABELS: dict[str, str] = {
    "used": "used",
    "no_recorded_use": "candidate",
    "rare_by_design": "rare by design",
    "too_new": "too new",
    "not_measured": "not measured",
    "retired": "retired",
}

DECISION_BADGES: dict[str, tuple[str, str]] = {
    "keep": ("keep", "green"),
    "later": ("snoozed", PREVIEW_STYLE),
    "cut": ("cut", FAULT_STYLE),
}

__all__ = [
    "COLD_MARKER",
    "DECISION_BADGES",
    "FAULT_STYLE",
    "MUTED_STYLE",
    "NOT_MEASURED_GLYPH",
    "NOT_MEASURED_STYLE",
    "PREVIEW_STYLE",
    "RECENT_7D_GLYPH",
    "RECENT_7D_STYLE",
    "RECENT_30D_GLYPH",
    "RECENT_30D_STYLE",
    "RECENT_WINDOW_GLYPH",
    "RECENT_WINDOW_STYLE",
    "STATE_GLYPHS",
    "STATE_LABELS",
    "ZERO_GLYPH",
    "ZERO_STYLE",
]

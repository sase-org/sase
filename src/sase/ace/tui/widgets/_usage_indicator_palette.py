"""Ten-bucket capacity color palette for the compact usage indicator.

Colors are calculated to exceed 4.5:1 contrast against the canonical dark
``#1E1E1E`` and light ``#E0E0E0`` surfaces (minimum approximately 5.64 and
4.66 respectively). The gradient conveys diminishing capacity without
treating a healthy 100% window as an alarm; fresh numeric windows use this
scale, while uncertain (stale/unknown-age) data uses neutral styling instead.
"""

from __future__ import annotations

import math

_DARK_BUCKET_COLORS: tuple[str, ...] = (
    "#FF5F6D",  # 0-<10%: nearly exhausted, red
    "#FF805F",  # 10-<20%: low, coral
    "#FFA552",  # 20-<30%: limited, orange
    "#EBC04F",  # 30-<40%: watchful, amber
    "#CED44C",  # 40-<50%: midrange, yellow
    "#AADC64",  # 50-<60%: comfortable, yellow-green
    "#78DB8D",  # 60-<70%: healthy, green
    "#4CD4B0",  # 70-<80%: ample, teal
    "#48CCD0",  # 80-<90%: abundant, cyan
    "#65C3ED",  # 90-100%: nearly full, blue
)

_LIGHT_BUCKET_COLORS: tuple[str, ...] = (
    "#A22534",
    "#A03620",
    "#8C480E",
    "#775800",
    "#5F6500",
    "#456C1B",
    "#206F3C",
    "#006E56",
    "#006C6C",
    "#006381",
)

NEUTRAL_DARK_COLOR = "#9E9E9E"
NEUTRAL_LIGHT_COLOR = "#5A5A5A"
WARNING_DARK_COLOR = "#FF8A5F"
WARNING_LIGHT_COLOR = "#A03620"
REJECTED_DARK_COLOR = "#FF5F6D"
REJECTED_LIGHT_COLOR = "#A22534"


def _usage_percent_bucket(remaining_percent: float) -> int:
    """Return the 0-9 capacity bucket for a clamped remaining percentage."""
    if not math.isfinite(remaining_percent):
        remaining_percent = 0.0
    clamped = max(0.0, min(100.0, remaining_percent))
    return min(9, int(clamped // 10))


def usage_percent_color(remaining_percent: float, *, dark: bool) -> str:
    """Return the ten-bucket percentage color for the active theme."""
    bucket = _usage_percent_bucket(remaining_percent)
    colors = _DARK_BUCKET_COLORS if dark else _LIGHT_BUCKET_COLORS
    return colors[bucket]


def usage_neutral_color(*, dark: bool) -> str:
    """Return the neutral color for stale/unknown-age percentage text."""
    return NEUTRAL_DARK_COLOR if dark else NEUTRAL_LIGHT_COLOR


def usage_secondary_style(*, dark: bool) -> str:
    """Return the readable secondary style for specifier and countdown text."""
    return usage_neutral_color(dark=dark)


def usage_warning_style(*, dark: bool) -> str:
    """Return the bold collector-failure marker style; never color-only."""
    return f"bold {WARNING_DARK_COLOR if dark else WARNING_LIGHT_COLOR}"


def usage_rejected_style(*, dark: bool) -> str:
    """Return the bold vendor-rejection marker style; never color-only."""
    return f"bold {REJECTED_DARK_COLOR if dark else REJECTED_LIGHT_COLOR}"


__all__ = [
    "NEUTRAL_DARK_COLOR",
    "NEUTRAL_LIGHT_COLOR",
    "usage_neutral_color",
    "usage_percent_color",
    "usage_rejected_style",
    "usage_secondary_style",
    "usage_warning_style",
]

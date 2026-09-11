"""Ten-bucket capacity color palette for the compact usage indicator.

Every usage badge paints an explicit background over its full extent, so
colors are calculated against that surface rather than the app's own
canonical shell surfaces. The badge surface is ``#242830`` (dark) and
``#E0E0E0`` (light); the gaps between and around badges keep the app's own
``#121212`` (dark) and ``#FAFAFA`` (light) background instead, so a badge
reads as a distinct rectangle. Against the badge surface, the ten-bucket
palette clears a minimum of approximately 5.00:1 (dark) and 4.66:1 (light);
the neutral text color clears approximately 8.06:1 (dark) and 5.89:1
(light). The gradient conveys diminishing capacity without treating a
healthy 100% window as an alarm; fresh numeric windows use this scale, while
uncertain (stale/unknown-age) data uses neutral styling instead.
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

BADGE_SURFACE_DARK_COLOR = "#242830"
BADGE_SURFACE_LIGHT_COLOR = "#E0E0E0"
GAP_SURFACE_DARK_COLOR = "#121212"
GAP_SURFACE_LIGHT_COLOR = "#FAFAFA"
NEUTRAL_DARK_COLOR = "#B8C0CC"
NEUTRAL_LIGHT_COLOR = "#4B535F"
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
    """Return the neutral color for stale/unknown-age value and specifier text."""
    return NEUTRAL_DARK_COLOR if dark else NEUTRAL_LIGHT_COLOR


def _usage_badge_surface_color(*, dark: bool) -> str:
    """Return the explicit background color painted behind a whole badge."""
    return BADGE_SURFACE_DARK_COLOR if dark else BADGE_SURFACE_LIGHT_COLOR


def _usage_gap_surface_color(*, dark: bool) -> str:
    """Return the neutral background color for the gaps around and between badges."""
    return GAP_SURFACE_DARK_COLOR if dark else GAP_SURFACE_LIGHT_COLOR


def usage_secondary_style(*, dark: bool) -> str:
    """Return the normal-weight style for provider-icon-fallback/specifier text."""
    return usage_neutral_color(dark=dark)


def usage_badge_base_style(*, dark: bool) -> str:
    """Return one badge's complete base style: neutral text on its own surface.

    Every character in a badge that isn't given a more specific style (icon,
    separators) renders with this base, and every span that is (percent,
    countdown, markers) layers its own color/weight on top of it without
    inheriting dim/reverse attributes from an unrelated ancestor style.
    """
    return (
        f"not bold not dim not reverse {usage_neutral_color(dark=dark)} "
        f"on {_usage_badge_surface_color(dark=dark)}"
    )


def usage_gap_style(*, dark: bool) -> str:
    """Return the explicit neutral background style for the existing badge gaps."""
    return f"not bold not dim not reverse on {_usage_gap_surface_color(dark=dark)}"


def usage_disclosure_style(*, dark: bool) -> str:
    """Return the bold neutral style for overflow/count disclosure text."""
    return f"bold {usage_neutral_color(dark=dark)} on {_usage_badge_surface_color(dark=dark)}"


def usage_value_style(color: str, *, dark: bool) -> str:
    """Return the bold value style for a window name, percent, and countdown."""
    return f"bold {color} on {_usage_badge_surface_color(dark=dark)}"


def usage_zero_percent_style(*, dark: bool) -> str:
    """Return the inverted exhausted style for an exact ``0%`` percentage token."""
    return (
        f"bold not dim not reverse {_usage_badge_surface_color(dark=dark)} "
        f"on {usage_percent_color(0, dark=dark)}"
    )


def usage_divider_style(color: str, *, dark: bool) -> str:
    """Return the normal-weight pipe style on the continuous provider surface."""
    return (
        f"not bold not dim not reverse {color} "
        f"on {_usage_badge_surface_color(dark=dark)}"
    )


def usage_rejected_style(*, dark: bool) -> str:
    """Return the bold vendor-rejection marker style; never color-only."""
    return f"bold {REJECTED_DARK_COLOR if dark else REJECTED_LIGHT_COLOR}"


__all__ = [
    "NEUTRAL_DARK_COLOR",
    "NEUTRAL_LIGHT_COLOR",
    "usage_badge_base_style",
    "usage_disclosure_style",
    "usage_divider_style",
    "usage_gap_style",
    "usage_neutral_color",
    "usage_percent_color",
    "usage_rejected_style",
    "usage_secondary_style",
    "usage_value_style",
    "usage_zero_percent_style",
]

"""Axis scaling and human-readable telemetry value formatting."""

from __future__ import annotations

import math
import textwrap
from datetime import UTC, datetime, tzinfo
from typing import Literal

from rich.cells import set_cell_size
from rich.text import Text

from sase.core.time import get_timezone
from sase.telemetry.render.palette import DARK_THEME, ChartTheme

ValueFormat = Literal["number", "duration", "tokens", "percent", "bytes"]
Timestamp = float | int | datetime


def format_value(value: float, value_format: ValueFormat = "number") -> str:
    """Format an axis or stat value without consulting locale or wall time."""

    if not math.isfinite(value):
        return "—"
    if value_format == "duration":
        return format_duration(value)
    if value_format == "tokens":
        return format_tokens(value)
    if value_format == "percent":
        return format_percentage(value)
    if value_format == "bytes":
        return format_bytes(value)
    return _format_compact(value)


def format_duration(seconds: float) -> str:
    """Return a compact duration suitable for an axis tick."""

    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    if seconds < 1:
        return f"{sign}{seconds * 1_000:.0f}ms"
    if seconds < 60:
        precision = 1 if seconds < 10 else 0
        return f"{sign}{seconds:.{precision}f}s"
    if seconds < 3_600:
        minutes = int(seconds // 60)
        rest = int(seconds % 60)
        return f"{sign}{minutes}m{rest:02d}s"
    if seconds < 86_400:
        hours = int(seconds // 3_600)
        minutes = int(seconds % 3_600 // 60)
        return f"{sign}{hours}h{minutes:02d}m"
    days = seconds / 86_400
    return f"{sign}{days:.1f}d"


def format_tokens(value: float) -> str:
    """Return a compact token count."""

    return _format_scaled(value, ("", "k", "M", "B", "T"))


def format_percentage(value: float) -> str:
    """Format a percentage value where ``5.2`` means 5.2 percent."""

    magnitude = abs(value)
    precision = 1 if magnitude < 100 else 0
    return f"{value:.{precision}f}%"


def format_bytes(value: float) -> str:
    """Return a compact binary byte count."""

    return _format_scaled(value, ("B", "KiB", "MiB", "GiB", "TiB"), base=1024)


def _timestamp_seconds(value: Timestamp) -> float:
    """Convert supported timestamps to Unix seconds deterministically."""

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()
    return float(value)


def format_recording_started(
    value: Timestamp | None, *, timezone: tzinfo | None = None
) -> str:
    """Build the shared labeled empty-state sentence."""

    if value is None:
        return "no samples in range"
    resolved_timezone = timezone or get_timezone()
    instant = datetime.fromtimestamp(_timestamp_seconds(value), tz=resolved_timezone)
    return (
        "no samples in range — telemetry began recording "
        f"{instant.strftime('%Y-%m-%d %H:%M %Z')}"
    )


def empty_state(
    recording_started_at: Timestamp | None,
    *,
    width: int,
    timezone: tzinfo | None = None,
    theme: ChartTheme = DARK_THEME,
    multiline: bool = False,
) -> Text:
    """Return the consistent, width-bounded empty-state renderable."""

    message = format_recording_started(recording_started_at, timezone=timezone)
    if multiline:
        bounded = "\n".join(
            textwrap.wrap(
                message,
                width=max(1, width),
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    else:
        bounded = set_cell_size(message, max(1, width))
    return Text(bounded, style=f"italic {theme.empty}", justify="center")


def _format_compact(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1_000:
        return _format_scaled(value, ("", "k", "M", "B", "T"))
    if magnitude < 0.01:
        return f"{value:.2e}"
    if magnitude < 10:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if magnitude < 100:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.0f}"


def _format_scaled(value: float, suffixes: tuple[str, ...], *, base: int = 1000) -> str:
    sign = "-" if value < 0 else ""
    scaled = abs(value)
    suffix_index = 0
    while scaled >= base and suffix_index < len(suffixes) - 1:
        scaled /= base
        suffix_index += 1
    precision = 1 if scaled < 10 and suffix_index else 0
    return f"{sign}{scaled:.{precision}f}{suffixes[suffix_index]}"

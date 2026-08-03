"""Compact deterministic block-glyph sparklines."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import tzinfo

from rich.cells import cell_len, set_cell_size
from rich.text import Text

from sase.core.time import get_timezone
from sase.telemetry.render.axis import (
    Timestamp,
    ValueFormat,
    empty_state,
    format_value,
)
from sase.telemetry.render.palette import (
    DARK_THEME,
    ChartTheme,
    categorical_color,
)

SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline_glyphs(values: Sequence[float], *, width: int) -> str:
    """Return exactly *width* spark glyphs, resampling values as needed."""

    if width <= 0:
        return ""
    finite = [float(value) for value in values if math.isfinite(value)]
    if not finite:
        return ""
    sampled = _resample(finite, width)
    low = min(sampled)
    high = max(sampled)
    if low == high:
        return SPARK_BLOCKS[3] * len(sampled)
    span = high - low
    return "".join(
        SPARK_BLOCKS[round((value - low) / span * (len(SPARK_BLOCKS) - 1))]
        for value in sampled
    )


def render_sparkline(
    values: Sequence[float],
    *,
    width: int,
    title: str = "",
    key: str = "sparkline",
    color: str | None = None,
    show_last: bool = True,
    value_format: ValueFormat = "number",
    recording_started_at: Timestamp | None = None,
    timezone: tzinfo | None = None,
    theme: ChartTheme = DARK_THEME,
) -> Text:
    """Render a one-row sparkline whose output is bounded to *width* cells."""

    timezone = timezone or get_timezone()
    width = max(1, width)
    finite = [float(value) for value in values if math.isfinite(value)]
    if not finite:
        return empty_state(
            recording_started_at,
            width=width,
            timezone=timezone,
            theme=theme,
        )

    prefix = f"{title}: " if title else ""
    suffix = f" {format_value(finite[-1], value_format)}" if show_last else ""
    reserved = cell_len(prefix) + cell_len(suffix)
    if reserved >= width:
        return Text(
            set_cell_size(f"{prefix}{suffix.lstrip()}", width),
            style=theme.foreground,
            no_wrap=True,
        )

    chart_width = width - reserved
    glyphs = sparkline_glyphs(finite, width=chart_width)
    output = Text(no_wrap=True, overflow="crop")
    if prefix:
        output.append(prefix, style=f"bold {theme.foreground}")
    output.append(glyphs, style=color or categorical_color(key))
    if suffix:
        output.append(suffix, style=theme.foreground)
    padding = width - cell_len(output.plain)
    if padding > 0:
        output.append(" " * padding)
    return output


def _resample(values: list[float], width: int) -> list[float]:
    if len(values) == width:
        return values
    if len(values) < width:
        if len(values) == 1:
            return values * width
        result: list[float] = []
        for index in range(width):
            position = index * (len(values) - 1) / max(1, width - 1)
            left = int(position)
            right = min(len(values) - 1, left + 1)
            fraction = position - left
            result.append(values[left] * (1 - fraction) + values[right] * fraction)
        return result

    result = []
    for index in range(width):
        start = index * len(values) // width
        end = max(start + 1, (index + 1) * len(values) // width)
        bucket = values[start:end]
        result.append(sum(bucket) / len(bucket))
    return result

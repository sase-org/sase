"""Smooth multi-series telemetry line charts built on a braille canvas."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo

from rich.align import Align
from rich.cells import cell_len, set_cell_size
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from sase.telemetry.render.axis import (
    Timestamp,
    ValueFormat,
    empty_state,
    endpoint_axis,
    format_value,
    normalize_bounds,
    scale,
    timestamp_seconds,
)
from sase.telemetry.render.braille import BrailleCanvas
from sase.telemetry.render.palette import (
    DARK_THEME,
    ChartTheme,
    categorical_color,
)
from sase.telemetry.render.sparkline import sparkline_glyphs


@dataclass(frozen=True, slots=True)
class Point:
    """One timestamped telemetry value."""

    timestamp: Timestamp
    value: float


@dataclass(frozen=True, slots=True)
class Series:
    """One stable, keyed line-chart series."""

    key: str
    points: tuple[Point, ...]
    label: str | None = None
    color: str | None = None

    @classmethod
    def from_pairs(
        cls,
        key: str,
        points: Sequence[tuple[Timestamp, float]],
        *,
        label: str | None = None,
        color: str | None = None,
    ) -> Series:
        """Build a series from query-friendly timestamp/value pairs."""

        return cls(
            key=key,
            points=tuple(Point(timestamp, float(value)) for timestamp, value in points),
            label=label,
            color=color,
        )

    @property
    def resolved_label(self) -> str:
        return self.label or self.key

    @property
    def resolved_color(self) -> str:
        return self.color or categorical_color(self.key)


LineSeries = Series
TimePoint = Point


def render_line_chart(
    series: Sequence[Series],
    *,
    title: str,
    width: int = 60,
    height: int = 14,
    y_label: str = "",
    value_format: ValueFormat = "number",
    y_min: float | None = None,
    y_max: float | None = None,
    recording_started_at: Timestamp | None = None,
    timezone: tzinfo = UTC,
    theme: ChartTheme = DARK_THEME,
) -> Panel:
    """Render keyed time series on one auto-scaled y-axis."""

    width = max(12, width)
    height = max(4, height)
    prepared = [(item, _finite_points(item)) for item in series]
    prepared = [(item, points) for item, points in prepared if points]
    if not prepared:
        message = empty_state(
            recording_started_at,
            width=max(1, width - 4),
            timezone=timezone,
            theme=theme,
            multiline=True,
        )
        return Panel(
            Align.center(message, vertical="middle"),
            title=title,
            border_style=theme.border,
            width=width,
            height=height,
            padding=0,
        )

    inner_width = width - 2
    inner_height = height - 2
    if inner_width < 30 or inner_height < 6:
        content = _compact_chart(
            prepared,
            width=inner_width,
            height=inner_height,
            theme=theme,
        )
    else:
        content = _braille_chart(
            prepared,
            width=inner_width,
            height=inner_height,
            y_label=y_label,
            value_format=value_format,
            y_min=y_min,
            y_max=y_max,
            timezone=timezone,
            theme=theme,
        )
    return Panel(
        content,
        title=title,
        border_style=theme.border,
        width=width,
        height=height,
        padding=0,
    )


def _finite_points(series: Series) -> list[tuple[float, float]]:
    points = [
        (timestamp_seconds(point.timestamp), float(point.value))
        for point in series.points
    ]
    return sorted(
        (
            (timestamp, value)
            for timestamp, value in points
            if math.isfinite(timestamp) and math.isfinite(value)
        ),
        key=lambda point: point[0],
    )


def _braille_chart(
    prepared: list[tuple[Series, list[tuple[float, float]]]],
    *,
    width: int,
    height: int,
    y_label: str,
    value_format: ValueFormat,
    y_min: float | None,
    y_max: float | None,
    timezone: tzinfo,
    theme: ChartTheme,
) -> Group:
    values = [value for _, points in prepared for _, value in points]
    timestamps = [timestamp for _, points in prepared for timestamp, _ in points]
    low, high = normalize_bounds(values, lower=y_min, upper=y_max)
    start, end = min(timestamps), max(timestamps)
    if start == end:
        start -= 60
        end += 60
    low_label = format_value(low, value_format)
    high_label = format_value(high, value_format)
    axis_width = min(max(cell_len(low_label), cell_len(high_label), 3), width // 3)
    legend_height = 1
    time_axis_height = 1
    canvas_height = max(1, height - legend_height - time_axis_height)
    canvas_width = max(1, width - axis_width - 1)
    canvas = BrailleCanvas(canvas_width, canvas_height)

    for item, points in prepared:
        scaled = [
            (
                scale(timestamp, start, end, canvas.dot_width),
                canvas.dot_height - 1 - scale(value, low, high, canvas.dot_height),
            )
            for timestamp, value in points
        ]
        canvas.draw_polyline(scaled, style=item.resolved_color)

    legend = Text(no_wrap=True, overflow="ellipsis")
    if y_label:
        legend.append(f"{y_label}  ", style=f"bold {theme.foreground}")
    for index, (item, _) in enumerate(prepared):
        if index:
            legend.append("  ")
        legend.append("●", style=item.resolved_color)
        legend.append(f" {item.resolved_label}", style=theme.foreground)
    legend.truncate(width, overflow="ellipsis")

    rows: list[Text] = [legend]
    canvas_rows = canvas.rows()
    for index, canvas_row in enumerate(canvas_rows):
        axis = Text(no_wrap=True)
        if index == 0:
            label = high_label
        elif index == len(canvas_rows) - 1:
            label = low_label
        else:
            label = ""
        axis.append(
            set_cell_size(label.rjust(axis_width), axis_width), style=theme.axis
        )
        axis.append("│", style=theme.axis)
        axis.append_text(canvas_row)
        rows.append(axis)

    time_axis = Text(" " * (axis_width + 1), no_wrap=True)
    time_axis.append(
        endpoint_axis(start, end, width=canvas_width, timezone=timezone),
        style=theme.axis,
    )
    rows.append(time_axis)
    return Group(*rows)


def _compact_chart(
    prepared: list[tuple[Series, list[tuple[float, float]]]],
    *,
    width: int,
    height: int,
    theme: ChartTheme,
) -> Group:
    visible = prepared[:height]
    label_width = min(
        max((cell_len(item.resolved_label) for item, _ in visible), default=1),
        max(1, width // 3),
    )
    spark_width = max(1, width - label_width - 1)
    rows: list[Text] = []
    for item, points in visible:
        row = Text(no_wrap=True, overflow="crop")
        row.append(
            set_cell_size(item.resolved_label, label_width),
            style=theme.foreground,
        )
        row.append(" ")
        row.append(
            sparkline_glyphs([value for _, value in points], width=spark_width),
            style=item.resolved_color,
        )
        rows.append(row)
    if len(prepared) > len(visible) and rows:
        rows[-1] = Text(
            set_cell_size(f"… +{len(prepared) - len(visible) + 1} more", width),
            style=theme.muted,
        )
    return Group(*rows)

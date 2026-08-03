"""Horizontal and vertical eighth-block telemetry bar charts."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import tzinfo
from typing import Literal

from rich.align import Align
from rich.cells import cell_len, set_cell_size
from rich.console import Group
from rich.panel import Panel
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
    Status,
    categorical_color,
    status_color,
)

Orientation = Literal["horizontal", "vertical"]

_HORIZONTAL_PARTIALS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")
_VERTICAL_PARTIALS = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")


@dataclass(frozen=True, slots=True)
class Bar:
    """One categorical value in a bar chart."""

    key: str
    label: str
    value: float
    color: str | None = None
    status: Status | None = None

    @property
    def resolved_color(self) -> str:
        if self.color:
            return self.color
        if self.status:
            return status_color(self.status)
        return categorical_color(self.key)


def render_bar_chart(
    bars: Sequence[Bar] | None = None,
    *,
    title: str,
    width: int = 60,
    height: int = 12,
    orientation: Orientation = "horizontal",
    labels: Sequence[str] | None = None,
    values: Sequence[float] | None = None,
    value_format: ValueFormat = "number",
    recording_started_at: Timestamp | None = None,
    timezone: tzinfo | None = None,
    theme: ChartTheme = DARK_THEME,
) -> Panel:
    """Render categorical values as a fixed-size Rich panel."""

    timezone = timezone or get_timezone()
    width = max(12, width)
    height = max(4, height)
    normalized = _normalize_bars(bars, labels=labels, values=values)
    normalized = [bar for bar in normalized if math.isfinite(bar.value)]
    if not normalized:
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

    if orientation == "vertical":
        content = _vertical_chart(
            normalized,
            width=width - 2,
            height=height - 2,
            value_format=value_format,
            theme=theme,
        )
    else:
        content = _horizontal_chart(
            normalized,
            width=width - 2,
            height=height - 2,
            value_format=value_format,
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


def _normalize_bars(
    bars: Sequence[Bar] | None,
    *,
    labels: Sequence[str] | None,
    values: Sequence[float] | None,
) -> list[Bar]:
    if bars is not None:
        return list(bars)
    if labels is None or values is None:
        return []
    return [
        Bar(key=label, label=label, value=float(value))
        for label, value in zip(labels, values, strict=False)
    ]


def _horizontal_chart(
    bars: list[Bar],
    *,
    width: int,
    height: int,
    value_format: ValueFormat,
    theme: ChartTheme,
) -> Group:
    visible = bars[:height]
    value_labels = [format_value(bar.value, value_format) for bar in visible]
    max_value_width = max(map(cell_len, value_labels), default=1)
    max_label_width = max((cell_len(bar.label) for bar in visible), default=1)
    label_width = min(max_label_width, 16, max(1, width // 3))
    bar_width = max(1, width - label_width - max_value_width - 3)
    maximum = max((abs(bar.value) for bar in visible), default=1.0) or 1.0
    rows: list[Text] = []
    for bar, value_label in zip(visible, value_labels, strict=True):
        ratio = abs(bar.value) / maximum
        glyphs = _horizontal_bar(ratio, bar_width)
        row = Text(no_wrap=True, overflow="crop")
        row.append(set_cell_size(bar.label, label_width), style=theme.foreground)
        row.append(" ")
        row.append(glyphs, style=bar.resolved_color)
        row.append(" " * max(0, bar_width - cell_len(glyphs)))
        row.append(" ")
        row.append(value_label.rjust(max_value_width), style=theme.foreground)
        rows.append(row)
    if len(bars) > len(visible) and rows:
        rows[-1] = Text(
            set_cell_size(f"… +{len(bars) - len(visible) + 1} more", width),
            style=theme.muted,
        )
    return Group(*rows)


def _vertical_chart(
    bars: list[Bar],
    *,
    width: int,
    height: int,
    value_format: ValueFormat,
    theme: ChartTheme,
) -> Group:
    chart_height = max(1, height - 1)
    axis_label = format_value(max(abs(bar.value) for bar in bars), value_format)
    axis_width = min(max(2, cell_len(axis_label)), max(2, width // 4))
    plot_width = max(1, width - axis_width - 1)
    max_bars = max(1, plot_width // 2)
    visible = bars[:max_bars]
    slot_width = max(1, plot_width // len(visible))
    maximum = max((abs(bar.value) for bar in visible), default=1.0) or 1.0
    totals = [round(abs(bar.value) / maximum * chart_height * 8) for bar in visible]

    rows: list[Text] = []
    for row_index in range(chart_height):
        row = Text(no_wrap=True, overflow="crop")
        axis = (
            set_cell_size(axis_label, axis_width)
            if row_index == 0
            else " " * axis_width
        )
        row.append(axis, style=theme.axis)
        row.append("┤" if row_index == 0 else "│", style=theme.axis)
        from_bottom = chart_height - row_index - 1
        for bar, total in zip(visible, totals, strict=True):
            cell_units = min(8, max(0, total - from_bottom * 8))
            glyph = _VERTICAL_PARTIALS[cell_units]
            row.append(glyph * slot_width, style=bar.resolved_color)
        rows.append(row)

    label_row = Text(" " * (axis_width + 1), no_wrap=True, overflow="crop")
    for bar in visible:
        label_row.append(set_cell_size(bar.label, slot_width), style=theme.foreground)
    if len(bars) > len(visible):
        label_row.append("…", style=theme.muted)
    rows.append(label_row)
    return Group(*rows)


def _horizontal_bar(ratio: float, width: int) -> str:
    eighths = min(width * 8, max(0, round(ratio * width * 8)))
    full, remainder = divmod(eighths, 8)
    if full >= width:
        return "█" * width
    return "█" * full + _HORIZONTAL_PARTIALS[remainder]

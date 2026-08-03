"""Rich stat tiles for telemetry summaries."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import tzinfo

from rich.align import Align
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
from sase.telemetry.render.sparkline import render_sparkline

_STATUS_GLYPHS: dict[Status, str] = {
    "ok": "✓",
    "warning": "!",
    "critical": "✕",
}


def render_stat_tile(
    value: float | str | None,
    *,
    caption: str,
    width: int = 24,
    height: int = 7,
    key: str | None = None,
    value_format: ValueFormat = "number",
    delta: float | None = None,
    lower_is_better: bool = False,
    sparkline: Sequence[float] | None = None,
    status: Status | None = None,
    recording_started_at: Timestamp | None = None,
    timezone: tzinfo | None = None,
    theme: ChartTheme = DARK_THEME,
) -> Panel:
    """Render a fixed-size value/caption/delta/sparkline summary tile."""

    timezone = timezone or get_timezone()
    width = max(12, width)
    height = max(4, height)
    color = status_color(status) if status else categorical_color(key or caption)
    if value is None or isinstance(value, float) and not math.isfinite(value):
        message = empty_state(
            recording_started_at,
            width=max(1, width - 4),
            timezone=timezone,
            theme=theme,
            multiline=True,
        )
        return Panel(
            Align.center(message, vertical="middle"),
            title=caption,
            border_style=color,
            width=width,
            height=height,
            padding=0,
        )

    formatted = value if isinstance(value, str) else format_value(value, value_format)
    value_line = Text(str(formatted), style=f"bold {color}", justify="center")
    body: list[Text] = [value_line]
    if status:
        body.append(
            Text(
                f"{_STATUS_GLYPHS[status]} {status}",
                style=f"bold {color}",
                justify="center",
            )
        )
    if delta is not None and math.isfinite(delta):
        body.append(
            Text(
                _format_delta(delta),
                style=_delta_style(delta, lower_is_better=lower_is_better, theme=theme),
                justify="center",
            )
        )
    if sparkline is not None:
        body.append(
            render_sparkline(
                sparkline,
                width=max(1, width - 4),
                key=key or caption,
                color=color,
                show_last=False,
                recording_started_at=recording_started_at,
                timezone=timezone,
                theme=theme,
            )
        )
    return Panel(
        Group(*body),
        title=caption,
        border_style=color,
        width=width,
        height=height,
        padding=(0, 1),
    )


def _format_delta(delta: float) -> str:
    arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
    return f"{arrow} {abs(delta):.1f}% vs previous"


def _delta_style(delta: float, *, lower_is_better: bool, theme: ChartTheme) -> str:
    if delta == 0:
        return theme.muted
    improving = delta < 0 if lower_is_better else delta > 0
    return status_color("ok" if improving else "critical")

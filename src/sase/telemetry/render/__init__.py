"""Deterministic Rich renderables shared by telemetry CLI and TUI surfaces."""

from sase.telemetry.render.axis import (
    Timestamp,
    ValueFormat,
    empty_state,
    format_bytes,
    format_duration,
    format_percentage,
    format_recording_started,
    format_tokens,
    format_value,
)
from sase.telemetry.render.bars import Bar, Orientation, render_bar_chart
from sase.telemetry.render.palette import (
    ADMIN_CENTER_ACCENTS,
    CATEGORICAL_COLORS,
    DARK_THEME,
    LIGHT_THEME,
    STATUS_COLORS,
    ChartTheme,
    Status,
    categorical_color,
    status_color,
    validate_palette,
)
from sase.telemetry.render.sparkline import (
    SPARK_BLOCKS,
    render_sparkline,
    sparkline_glyphs,
)
from sase.telemetry.render.tiles import render_stat_tile

__all__ = [
    "ADMIN_CENTER_ACCENTS",
    "CATEGORICAL_COLORS",
    "DARK_THEME",
    "LIGHT_THEME",
    "SPARK_BLOCKS",
    "STATUS_COLORS",
    "Bar",
    "ChartTheme",
    "Orientation",
    "Status",
    "Timestamp",
    "ValueFormat",
    "categorical_color",
    "empty_state",
    "format_bytes",
    "format_duration",
    "format_percentage",
    "format_recording_started",
    "format_tokens",
    "format_value",
    "render_bar_chart",
    "render_sparkline",
    "render_stat_tile",
    "sparkline_glyphs",
    "status_color",
    "validate_palette",
]

"""Python presentation facade for historical SASE statistics."""

from sase.stats.query import query_activity_stats, query_run_stats
from sase.stats.ranges import (
    DEFAULT_PRESET,
    PRESETS,
    PRESET_ORDER,
    PresetKey,
    RangePreset,
    StatsRange,
    parse_custom_range,
    resolve_preset,
)
from sase.stats.views import StatisticsViews, build_statistics_views

__all__ = [
    "DEFAULT_PRESET",
    "PRESETS",
    "PRESET_ORDER",
    "PresetKey",
    "RangePreset",
    "StatisticsViews",
    "StatsRange",
    "build_statistics_views",
    "parse_custom_range",
    "query_activity_stats",
    "query_run_stats",
    "resolve_preset",
]

"""Compatibility re-exports for Statistics pane types and the shared loader."""

from __future__ import annotations

from sase.stats.loader import StatisticsViewData, load_statistics_view
from sase.stats.registry import (
    MACROS_GROUP_ORDER,
    PERF_GROUP_ORDER,
    PROJECTS_GROUP_ORDER,
    STATISTICS_VIEW_BY_ID,
    STATISTICS_VIEW_SPECS,
    VIEW_COMPACT_LABELS,
    VIEW_DESCRIPTIONS,
    VIEW_LABELS,
    VIEW_MICRO_LABELS,
    VIEW_ORDER,
    MacrosGroupBy,
    MetricLegend,
    PerfGroupBy,
    ProjectsGroupBy,
    StatisticsGrouping,
    StatisticsView,
    StatisticsViewSpec,
    statistics_view_description_text,
    statistics_view_supports_grouping,
    validated_statistics_view,
)

__all__ = [
    "MACROS_GROUP_ORDER",
    "PERF_GROUP_ORDER",
    "PROJECTS_GROUP_ORDER",
    "STATISTICS_VIEW_BY_ID",
    "STATISTICS_VIEW_SPECS",
    "VIEW_COMPACT_LABELS",
    "VIEW_DESCRIPTIONS",
    "VIEW_LABELS",
    "VIEW_MICRO_LABELS",
    "VIEW_ORDER",
    "MacrosGroupBy",
    "MetricLegend",
    "PerfGroupBy",
    "ProjectsGroupBy",
    "StatisticsGrouping",
    "StatisticsView",
    "StatisticsViewData",
    "StatisticsViewSpec",
    "load_statistics_view",
    "statistics_view_description_text",
    "statistics_view_supports_grouping",
    "validated_statistics_view",
]

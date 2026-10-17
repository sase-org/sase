"""Textual-free Projects report API shared by the CLI and TUI."""

from .loader import load_project_stats
from .query import (
    ALL_FACETS,
    ProjectStatsFacet,
    ProjectStatsGrouping,
    ProjectStatsQuery,
    ProjectStatsUnavailableError,
    ProjectStatsUsageError,
)
from .view import ProjectStatsView

__all__ = [
    "ALL_FACETS",
    "ProjectStatsFacet",
    "ProjectStatsGrouping",
    "ProjectStatsQuery",
    "ProjectStatsUnavailableError",
    "ProjectStatsUsageError",
    "ProjectStatsView",
    "load_project_stats",
]

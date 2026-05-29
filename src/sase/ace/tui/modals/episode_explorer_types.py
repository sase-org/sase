"""Shared types for the Episode Explorer modal."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from sase.memory.episodes.inventory import EpisodeInventoryItem


EpisodeExplorerView = Literal["overview", "timeline", "graph", "sources", "agent"]
EpisodeExplorerRange = Literal["all", "today", "yesterday", "week", "month"]
EpisodeExplorerBand = Literal["all", "high", "medium", "low", "unknown"]
EpisodeExplorerStatus = Literal["all", "v2", "v1", "aliases"]
EpisodeExplorerEdgeMode = Literal["strong", "all"]

RANGES: tuple[EpisodeExplorerRange, ...] = (
    "all",
    "today",
    "yesterday",
    "week",
    "month",
)
BANDS: tuple[EpisodeExplorerBand, ...] = ("all", "high", "medium", "low", "unknown")
STATUSES: tuple[EpisodeExplorerStatus, ...] = ("all", "v2", "v1", "aliases")
VIEWS: tuple[EpisodeExplorerView, ...] = (
    "overview",
    "timeline",
    "graph",
    "sources",
    "agent",
)
WORKER_GROUP = "episode-explorer"


@dataclass(frozen=True)
class EpisodeExplorerFilters:
    """Current inventory filters."""

    quick_range: EpisodeExplorerRange = "week"
    query: str = ""
    band: EpisodeExplorerBand = "all"
    agent: str = ""
    changespec: str = ""
    bead: str = ""
    status: EpisodeExplorerStatus = "all"


@dataclass(frozen=True)
class EpisodeExplorerDisplayRow:
    """One selectable row in the left inventory pane."""

    item: EpisodeInventoryItem
    display_episode_id: str
    canonical_episode_id: str
    is_alias: bool = False
    alias_reason: str = ""


@dataclass(frozen=True)
class EpisodeExplorerLoadResult:
    """Background inventory load result."""

    project: str
    items: list[EpisodeInventoryItem]
    error: str | None = None


def replace_filters(
    filters: EpisodeExplorerFilters,
    **changes: Any,
) -> EpisodeExplorerFilters:
    return replace(filters, **changes)


def cycle_value[T: str](
    values: tuple[T, ...],
    current: T,
    *,
    step: int = 1,
) -> T:
    try:
        index = values.index(current)
    except ValueError:
        return values[0]
    return values[(index + step) % len(values)]


__all__ = [
    "BANDS",
    "EpisodeExplorerDisplayRow",
    "EpisodeExplorerFilters",
    "EpisodeExplorerLoadResult",
    "EpisodeExplorerBand",
    "EpisodeExplorerEdgeMode",
    "EpisodeExplorerRange",
    "EpisodeExplorerStatus",
    "EpisodeExplorerView",
    "RANGES",
    "STATUSES",
    "VIEWS",
    "WORKER_GROUP",
    "cycle_value",
    "replace_filters",
]

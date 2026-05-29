"""Filtering helpers for the ACE Episode Explorer modal."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Literal

from sase.memory.episodes._collector_utils import compact_timestamp
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


def display_rows(
    items: list[EpisodeInventoryItem],
    status: EpisodeExplorerStatus,
) -> list[EpisodeExplorerDisplayRow]:
    rows: list[EpisodeExplorerDisplayRow] = []
    for item in items:
        if status != "aliases":
            rows.append(
                EpisodeExplorerDisplayRow(
                    item=item,
                    display_episode_id=item.row.episode_id,
                    canonical_episode_id=item.row.episode_id,
                )
            )
        if status in {"all", "aliases"}:
            for alias in item.aliases:
                rows.append(
                    EpisodeExplorerDisplayRow(
                        item=item,
                        display_episode_id=alias.alias_episode_id,
                        canonical_episode_id=alias.canonical_episode_id,
                        is_alias=True,
                        alias_reason=alias.reason,
                    )
                )
    return rows


def matches_filters(
    item: EpisodeInventoryItem,
    filters: EpisodeExplorerFilters,
    *,
    today: date,
) -> bool:
    if filters.band != "all" and item.row.importance_band.lower() != filters.band:
        return False
    if filters.status == "v1" and item.version != "v1":
        return False
    if filters.status == "v2" and item.version != "v2":
        return False
    if filters.status == "aliases" and not item.aliases:
        return False
    since, until = range_bounds(filters.quick_range, today=today)
    if not _matches_date_window(item, since=since, until=until):
        return False
    if not _contains_all(_agent_haystack(item), filters.agent):
        return False
    if not _contains_all(item.row.changespec_name or "", filters.changespec):
        return False
    if not _contains_all(" ".join(item.row.bead_ids), filters.bead):
        return False
    return _contains_all(_query_haystack(item), filters.query)


def range_bounds(
    quick_range: EpisodeExplorerRange,
    *,
    today: date,
) -> tuple[str | None, str | None]:
    if quick_range == "all":
        return None, None
    if quick_range == "today":
        text = today.isoformat()
        return text, text
    if quick_range == "yesterday":
        text = (today - timedelta(days=1)).isoformat()
        return text, text
    if quick_range == "week":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    first = today.replace(day=1)
    return first.isoformat(), today.isoformat()


def _matches_date_window(
    item: EpisodeInventoryItem,
    *,
    since: str | None,
    until: str | None,
) -> bool:
    if since is None and until is None:
        return True
    row = item.row
    start = row.first_event_at or row.last_event_at
    end = row.last_event_at or row.first_event_at
    if start is None or end is None:
        return False
    start_key = compact_timestamp(start)
    end_key = compact_timestamp(end)
    if since is not None and end_key < since.replace("-", "") + "000000":
        return False
    if until is not None and start_key > until.replace("-", "") + "235959":
        return False
    return True


def _contains_all(haystack: str, query: str) -> bool:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return True
    folded = haystack.casefold()
    return all(term in folded for term in terms)


def _agent_haystack(item: EpisodeInventoryItem) -> str:
    return " ".join(item.row.root_agent_names)


def _query_haystack(item: EpisodeInventoryItem) -> str:
    row = item.row
    return " ".join(
        [
            row.episode_id,
            row.title,
            row.summary_excerpt,
            row.component_key,
            row.status,
            row.importance_band,
            row.changespec_name or "",
            row.outcome or "",
            " ".join(row.root_agent_names),
            " ".join(row.bead_ids),
            " ".join(alias.alias_episode_id for alias in item.aliases),
            " ".join(item.warnings),
            item.version,
        ]
    )


__all__ = [
    "BANDS",
    "RANGES",
    "STATUSES",
    "VIEWS",
    "EpisodeExplorerBand",
    "EpisodeExplorerDisplayRow",
    "EpisodeExplorerEdgeMode",
    "EpisodeExplorerFilters",
    "EpisodeExplorerLoadResult",
    "EpisodeExplorerRange",
    "EpisodeExplorerStatus",
    "EpisodeExplorerView",
    "cycle_value",
    "display_rows",
    "matches_filters",
    "range_bounds",
    "replace_filters",
]

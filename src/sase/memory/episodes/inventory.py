"""Episode inventory query helpers for CLI and future UI surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Literal

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeStorageIndexRowWire,
    EpisodeWire,
    episode_wire_from_dict,
    episode_wire_to_json_dict,
)
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.identity import (
    EpisodeAliasIndexRow,
    aliases_by_canonical_episode_id,
    read_episode_alias_rows,
    resolve_alias_episode_id,
)
from sase.memory.episodes.index import project_episodes_dir, read_episode_index
from sase.memory.episodes.storage import EPISODE_JSON_FILE_NAME

EpisodeInventoryGroup = Literal["day", "week", "none"]
EpisodeInventoryOrder = Literal["time", "importance", "title"]


@dataclass(frozen=True)
class EpisodeInventoryItem:
    """One canonical episode row enriched for inventory display."""

    row: EpisodeStorageIndexRowWire
    aliases: list[EpisodeAliasIndexRow]
    warnings: list[str]
    version: str
    is_legacy: bool

    def to_json_dict(self) -> dict[str, Any]:
        payload = episode_wire_to_json_dict(self.row)
        payload.update(
            {
                "alias_episode_ids": [alias.alias_episode_id for alias in self.aliases],
                "aliases": [episode_wire_to_json_dict(alias) for alias in self.aliases],
                "is_alias": False,
                "is_legacy": self.is_legacy,
                "version": self.version,
                "warnings": list(self.warnings),
            }
        )
        return payload


def query_episode_inventory(
    project: str,
    *,
    projects_root: Path | str | None = None,
    since: str | None = None,
    until: str | None = None,
    band: str | None = None,
    agent: str | None = None,
    changespec: str | None = None,
    bead: str | None = None,
    query: str | None = None,
    order: EpisodeInventoryOrder = "time",
    limit: int | None = None,
) -> list[EpisodeInventoryItem]:
    """Return deterministic inventory rows after applying CLI filters."""

    alias_rows = read_episode_alias_rows(project, projects_root=projects_root)
    alias_ids = {row.alias_episode_id for row in alias_rows}
    aliases_by_canonical = aliases_by_canonical_episode_id(
        project,
        projects_root=projects_root,
    )
    rows = [
        row
        for row in read_episode_index(project, projects_root=projects_root)
        if row.episode_id not in alias_ids
        and resolve_alias_episode_id(row.episode_id, alias_rows) == row.episode_id
    ]
    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    items = [
        _inventory_item(
            row,
            aliases=aliases_by_canonical.get(row.episode_id, []),
            episode=_load_episode_or_none(episodes_dir / row.episode_id),
        )
        for row in rows
    ]
    filtered = [
        item
        for item in items
        if _matches_date_window(item.row, since=since, until=until)
        and _matches_band(item.row, band)
        and _matches_agent(item.row, agent)
        and _matches_changespec(item.row, changespec)
        and _matches_bead(item.row, bead)
        and _matches_query(item, query)
    ]
    ordered = _order_items(filtered, order)
    return ordered if limit is None else ordered[:limit]


def group_inventory_items(
    items: list[EpisodeInventoryItem],
    group: EpisodeInventoryGroup,
) -> list[tuple[str | None, list[EpisodeInventoryItem]]]:
    """Group inventory items by event date bucket."""

    if group == "none":
        return [(None, items)]
    groups: dict[str, list[EpisodeInventoryItem]] = {}
    for item in items:
        key = _group_key(item.row, group)
        groups.setdefault(key, []).append(item)
    return [(key, groups[key]) for key in sorted(groups)]


def canonical_index_rows(
    project: str,
    projects_root: Path | str | None,
) -> list[EpisodeStorageIndexRowWire]:
    """Return canonical, non-alias index rows for compatibility callers."""

    return [
        item.row
        for item in query_episode_inventory(
            project,
            projects_root=projects_root,
            order="time",
        )
    ]


def _inventory_item(
    row: EpisodeStorageIndexRowWire,
    *,
    aliases: list[EpisodeAliasIndexRow],
    episode: EpisodeWire | None,
) -> EpisodeInventoryItem:
    version = _episode_version(row, episode)
    is_legacy = version == "v1" or row.status == "legacy"
    warnings = sorted(set(episode.safety.warnings if episode is not None else []))
    return EpisodeInventoryItem(
        row=row,
        aliases=aliases,
        warnings=warnings,
        version=version,
        is_legacy=is_legacy,
    )


def _episode_version(
    row: EpisodeStorageIndexRowWire,
    episode: EpisodeWire | None,
) -> str:
    if episode is not None:
        if episode.schema_version < EPISODE_WIRE_SCHEMA_VERSION:
            return "v1"
        if episode.status == "legacy" or not episode.component_key:
            return "v1"
        return "v2"
    if row.schema_version < EPISODE_WIRE_SCHEMA_VERSION:
        return "v1"
    return "v2" if row.component_key and row.status != "legacy" else "v1"


def _load_episode_or_none(episode_dir: Path) -> EpisodeWire | None:
    try:
        data = json.loads(
            (episode_dir / EPISODE_JSON_FILE_NAME).read_text(encoding="utf-8")
        )
        return episode_wire_from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _matches_date_window(
    row: EpisodeStorageIndexRowWire,
    *,
    since: str | None,
    until: str | None,
) -> bool:
    if since is None and until is None:
        return True
    start = row.first_event_at or row.last_event_at
    end = row.last_event_at or row.first_event_at
    if start is None or end is None:
        return False
    start_key = compact_timestamp(start)
    end_key = compact_timestamp(end)
    if since is not None and end_key < _range_bound(since, end=False):
        return False
    if until is not None and start_key > _range_bound(until, end=True):
        return False
    return True


def _range_bound(value: str, *, end: bool) -> str:
    stripped = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        return stripped.replace("-", "") + ("235959" if end else "000000")
    return compact_timestamp(stripped)


def _matches_band(row: EpisodeStorageIndexRowWire, band: str | None) -> bool:
    return band is None or row.importance_band.lower() == band.lower()


def _matches_agent(row: EpisodeStorageIndexRowWire, agent: str | None) -> bool:
    if agent is None:
        return True
    needle = agent.lower()
    return any(needle in name.lower() for name in row.root_agent_names)


def _matches_changespec(
    row: EpisodeStorageIndexRowWire,
    changespec: str | None,
) -> bool:
    if changespec is None:
        return True
    return changespec.lower() in (row.changespec_name or "").lower()


def _matches_bead(row: EpisodeStorageIndexRowWire, bead: str | None) -> bool:
    if bead is None:
        return True
    needle = bead.lower()
    return any(needle in bead_id.lower() for bead_id in row.bead_ids)


def _matches_query(item: EpisodeInventoryItem, query: str | None) -> bool:
    terms = [term.lower() for term in (query or "").split() if term.strip()]
    if not terms:
        return True
    haystack = _query_haystack(item).lower()
    return all(term in haystack for term in terms)


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
            " ".join(row.root_agent_names),
            row.changespec_name or "",
            " ".join(row.bead_ids),
            row.outcome or "",
            " ".join(alias.alias_episode_id for alias in item.aliases),
            " ".join(item.warnings),
            item.version,
        ]
    )


def _order_items(
    items: list[EpisodeInventoryItem],
    order: EpisodeInventoryOrder,
) -> list[EpisodeInventoryItem]:
    if order == "importance":
        return sorted(
            items,
            key=lambda item: (
                -item.row.importance_score,
                _time_sort_key(item.row),
                item.row.title.lower(),
                item.row.episode_id,
            ),
        )
    if order == "title":
        return sorted(
            items,
            key=lambda item: (
                item.row.title.lower(),
                _time_sort_key(item.row),
                item.row.episode_id,
            ),
        )
    return sorted(
        items,
        key=lambda item: (
            _time_sort_key(item.row),
            item.row.title.lower(),
            item.row.episode_id,
        ),
    )


def _time_sort_key(row: EpisodeStorageIndexRowWire) -> tuple[str, str]:
    return (
        compact_timestamp(row.first_event_at or row.last_event_at or "99999999999999"),
        compact_timestamp(row.last_event_at or row.first_event_at or "99999999999999"),
    )


def _group_key(
    row: EpisodeStorageIndexRowWire,
    group: EpisodeInventoryGroup,
) -> str:
    timestamp = row.first_event_at or row.last_event_at
    if timestamp is None:
        return "undated"
    compact = compact_timestamp(timestamp)
    if len(compact) < 8 or not compact[:8].isdigit():
        return "undated"
    day = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    if group == "day":
        return day
    from datetime import datetime

    try:
        iso = datetime.strptime(day, "%Y-%m-%d").isocalendar()
    except ValueError:
        return "undated"
    return f"{iso.year}-W{iso.week:02d}"


__all__ = [
    "EpisodeInventoryGroup",
    "EpisodeInventoryItem",
    "EpisodeInventoryOrder",
    "canonical_index_rows",
    "group_inventory_items",
    "query_episode_inventory",
]

"""Helpers for preserving xprompt discovery precedence in ordered catalogs."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Protocol


class _DiscoveryRanked(Protocol):
    """Object carrying the loader-assigned discovery rank."""

    discovery_rank: int | None


RANK_UNSPECIFIED = 0
RANK_PACKAGE_XPROMPTS = 100
RANK_PACKAGE_DEFAULT_XPROMPTS = 110
RANK_PACKAGE_SKILLS = 120
RANK_PLUGIN = 200
RANK_PLUGIN_SKILLS = 210
RANK_CONFIG_BASE = 300
RANK_PROJECT_CONFIG = 390
RANK_FILESYSTEM_BASE = 500
RANK_REGISTERED_PROJECT_BASE = 700
RANK_MEMORY_BASE = 800
RANK_SKILL_FILES_BASE = 900


def discovery_rank(item: _DiscoveryRanked, fallback: int = RANK_UNSPECIFIED) -> int:
    """Return *item*'s discovery rank, assigning *fallback* when absent."""
    rank = item.discovery_rank
    if rank is None:
        item.discovery_rank = fallback
        return fallback
    return rank


def assign_discovery_rank[T: _DiscoveryRanked](
    items: Mapping[str, T], rank: int
) -> dict[str, T]:
    """Assign *rank* to every item in a newly loaded source bucket."""
    for item in items.values():
        item.discovery_rank = rank
    return dict(items)


def source_rank(base: int, source_index: int, source_count: int) -> int:
    """Return an increasing rank for a first-wins source list.

    Source lists arrive in highest-to-lowest precedence order. Catalog maps are
    assembled lowest-to-highest, so the first source receives the largest rank.
    """
    return base + source_count - source_index


def merge_by_discovery_order[T: _DiscoveryRanked](
    target: MutableMapping[str, T],
    source: Mapping[str, T],
    *,
    fallback_rank: int = RANK_UNSPECIFIED,
) -> None:
    """Merge *source* into *target*, moving replacements to their priority slot."""
    entries = [
        (discovery_rank(item, fallback_rank), index, name, item)
        for index, (name, item) in enumerate(source.items())
    ]
    for _, _, name, item in sorted(entries, key=lambda entry: (entry[0], entry[1])):
        if name in target:
            del target[name]
        target[name] = item


__all__ = [
    "RANK_CONFIG_BASE",
    "RANK_FILESYSTEM_BASE",
    "RANK_MEMORY_BASE",
    "RANK_PACKAGE_DEFAULT_XPROMPTS",
    "RANK_PACKAGE_SKILLS",
    "RANK_PACKAGE_XPROMPTS",
    "RANK_PLUGIN",
    "RANK_PLUGIN_SKILLS",
    "RANK_PROJECT_CONFIG",
    "RANK_REGISTERED_PROJECT_BASE",
    "RANK_SKILL_FILES_BASE",
    "RANK_UNSPECIFIED",
    "assign_discovery_rank",
    "discovery_rank",
    "merge_by_discovery_order",
    "source_rank",
]

"""Public data model and load orchestration for the SASE plugin catalog.

This is the only module Phases 2 & 3 (the ``sase plugin list`` / ``sase plugin
show`` CLI) consume: :func:`load_plugin_catalog`, :func:`find_plugin`,
:func:`suggest_plugins`, and the :class:`PluginCatalog` / :class:`PluginCatalogEntry`
model. The GitHub source, the on-disk cache, and the installed-merge details stay
behind this facade.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

from sase.plugins.cache import (
    CachedCatalog,
    cache_age_seconds,
    is_cache_stale,
    read_cache,
    write_cache,
)
from sase.plugins.github_source import (
    CatalogFetchResult,
    GH_SEARCH_QUERY,
    GhNotFoundError,
    PluginCatalogError,
    fetch_catalog_payload,
)
from sase.plugins.installed import (
    InstalledInfo,
    build_installed_index,
    lookup_installed,
)
from sase.plugins.latest import LatestInfo, is_newer

#: The canonical GitHub org. Repos owned here are "built-in"; everyone else is
#: "community" (rendered with a warning). A module constant for now; may later be
#: configurable (see the epic's Out of Scope notes).
SASE_PLUGIN_ORG = "sase-org"

PluginKind = Literal["builtin", "community"]

#: A suggestion must clear this fuzzy-match ratio to be offered on a miss.
_SUGGESTION_THRESHOLD = 0.3

FetchFn = Callable[[], list[dict[str, Any]] | CatalogFetchResult]
ReadCacheFn = Callable[[], CachedCatalog | None]
WriteCacheFn = Callable[..., None]
InstalledIndexFn = Callable[[], dict[str, InstalledInfo]]


@dataclass(frozen=True)
class PluginCatalogEntry:
    """One plugin in the catalog, merged with local installed status."""

    name: str
    repo: str
    full_name: str
    owner: str
    description: str
    url: str
    homepage: str
    topics: tuple[str, ...]
    stars: int
    archived: bool
    license: str
    updated_at: str
    installed: InstalledInfo = field(default_factory=InstalledInfo.not_installed)
    latest: LatestInfo = field(default_factory=LatestInfo.unknown)

    @property
    def kind(self) -> PluginKind:
        return "builtin" if self.owner.casefold() == SASE_PLUGIN_ORG else "community"

    @property
    def is_builtin(self) -> bool:
        return self.kind == "builtin"

    @property
    def is_community(self) -> bool:
        return self.kind == "community"

    @property
    def update_available(self) -> bool:
        """Return whether an installed plugin is behind its latest version."""
        if not self.installed.installed:
            return False
        if self.latest.source == "editable":
            return self.latest.update_available
        return self.latest.source == "index" and is_newer(
            self.latest.version, self.installed.version
        )


@dataclass(frozen=True)
class PluginCatalog:
    """The loaded catalog plus freshness metadata for rendering."""

    fetched_at: float
    entries: tuple[PluginCatalogEntry, ...]
    from_cache: bool
    stale: bool
    query: str = GH_SEARCH_QUERY
    warnings: tuple[str, ...] = ()

    def age_seconds(self, now: float | None = None) -> float:
        now = time.time() if now is None else now
        return cache_age_seconds(self.fetched_at, now)

    @property
    def builtin_entries(self) -> tuple[PluginCatalogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_builtin)

    @property
    def community_entries(self) -> tuple[PluginCatalogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_community)

    @property
    def installed_count(self) -> int:
        return sum(1 for entry in self.entries if entry.installed.installed)

    @property
    def updates_available(self) -> int:
        return sum(1 for entry in self.entries if entry.update_available)


def load_plugin_catalog(
    *,
    refresh: bool = False,
    offline: bool = False,
    now: float | None = None,
    fetch_fn: FetchFn = fetch_catalog_payload,
    read_cache_fn: ReadCacheFn = read_cache,
    write_cache_fn: WriteCacheFn = write_cache,
    installed_index_fn: InstalledIndexFn = build_installed_index,
) -> PluginCatalog:
    """Load the plugin catalog, merged with installed status.

    Cache-first by default: a query-compatible cache is used and the network is
    never touched unless ``refresh`` is set or no compatible cache exists. When
    a refresh/first fetch fails because ``gh`` ran but errored, a compatible
    cache is used as a stale fallback with a loud warning; a missing ``gh`` (or
    no compatible cache at all) raises :class:`PluginCatalogError`.
    """
    now = time.time() if now is None else now
    cached = read_cache_fn()
    compatible_cached = _compatible_cache(cached)
    warnings: list[str] = []

    if offline:
        if compatible_cached is None:
            raise PluginCatalogError(_offline_cache_error(cached))
        payload = list(compatible_cached.entries)
        fetched_at = compatible_cached.fetched_at
        from_cache = True
    elif refresh or compatible_cached is None:
        payload, fetched_at, from_cache = _fetch_or_fall_back(
            fetch_fn=fetch_fn,
            write_cache_fn=write_cache_fn,
            cached=compatible_cached,
            now=now,
            warnings=warnings,
        )
    else:
        payload = list(compatible_cached.entries)
        fetched_at = compatible_cached.fetched_at
        from_cache = True

    index = installed_index_fn()
    entries = _build_entries(payload, index)

    return PluginCatalog(
        fetched_at=fetched_at,
        entries=entries,
        from_cache=from_cache,
        stale=is_cache_stale(fetched_at, now),
        warnings=tuple(warnings),
    )


def _compatible_cache(cached: CachedCatalog | None) -> CachedCatalog | None:
    if cached is None or cached.query != GH_SEARCH_QUERY:
        return None
    return cached


def _offline_cache_error(cached: CachedCatalog | None) -> str:
    suffix = "run `sase plugin list --refresh` when online"
    if cached is None:
        return f"plugin catalog cache is unavailable in offline mode; {suffix}"
    actual = cached.query or "missing query"
    return (
        "plugin catalog cache is incompatible with the current GitHub repository "
        f"topic query ({actual}; expected {GH_SEARCH_QUERY}); {suffix}"
    )


def _fetch_or_fall_back(
    *,
    fetch_fn: FetchFn,
    write_cache_fn: WriteCacheFn,
    cached: CachedCatalog | None,
    now: float,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], float, bool]:
    try:
        fetched = _as_fetch_result(fetch_fn())
    except GhNotFoundError:
        # A missing gh is always a hard error: never silently serve stale data
        # without the user knowing the CLI they need is absent.
        raise
    except PluginCatalogError as exc:
        if cached is None:
            raise
        warnings.append(
            f"showing stale cached plugin data: could not refresh from GitHub ({exc})"
        )
        return list(cached.entries), cached.fetched_at, True

    warnings.extend(fetched.warnings)
    write_cache_fn(fetched.entries, fetched_at=now, query=GH_SEARCH_QUERY)
    return fetched.entries, now, False


def _as_fetch_result(
    value: list[dict[str, Any]] | CatalogFetchResult,
) -> CatalogFetchResult:
    if isinstance(value, CatalogFetchResult):
        return value
    return CatalogFetchResult(entries=value)


def _build_entries(
    payload: list[dict[str, Any]],
    index: dict[str, InstalledInfo],
) -> tuple[PluginCatalogEntry, ...]:
    entries = [_merge_entry(_entry_from_payload(item), index) for item in payload]
    # Built-in first, then community; alphabetical by short name within each.
    entries.sort(key=lambda entry: (entry.kind != "builtin", entry.name.casefold()))
    return tuple(entries)


def _entry_from_payload(item: dict[str, Any]) -> PluginCatalogEntry:
    return PluginCatalogEntry(
        name=_str(item.get("name")),
        repo=_str(item.get("repo")),
        full_name=_str(item.get("full_name")),
        owner=_str(item.get("owner")),
        description=_str(item.get("description")),
        url=_str(item.get("url")),
        homepage=_str(item.get("homepage")),
        topics=tuple(t for t in item.get("topics", ()) if isinstance(t, str)),
        stars=_int(item.get("stars")),
        archived=bool(item.get("archived")),
        license=_str(item.get("license")),
        updated_at=_str(item.get("updated_at")),
    )


def _merge_entry(
    entry: PluginCatalogEntry,
    index: dict[str, InstalledInfo],
) -> PluginCatalogEntry:
    info = lookup_installed(index, repo=entry.repo, name=entry.name)
    return dataclasses.replace(entry, installed=info)


def find_plugin(catalog: PluginCatalog, query: str) -> PluginCatalogEntry | None:
    """Return the entry exactly matching *query*, or ``None``.

    Matching is case-insensitive against the short name (``github``), the repo
    (``sase-github``), and the full name (``sase-org/sase-github``).
    """
    needle = query.strip().casefold()
    if not needle:
        return None
    for entry in catalog.entries:
        if needle in {
            entry.name.casefold(),
            entry.repo.casefold(),
            entry.full_name.casefold(),
        }:
            return entry
    return None


def suggest_plugins(
    catalog: PluginCatalog,
    query: str,
    *,
    limit: int = 3,
) -> tuple[PluginCatalogEntry, ...]:
    """Return up to *limit* ranked "did you mean…?" suggestions for a miss."""
    needle = query.strip().casefold()
    if not needle:
        return ()

    scored: list[tuple[float, str, PluginCatalogEntry]] = []
    for entry in catalog.entries:
        targets = (
            entry.name.casefold(),
            entry.repo.casefold(),
            entry.full_name.casefold(),
        )
        score = max(SequenceMatcher(None, needle, target).ratio() for target in targets)
        if any(needle in target for target in targets):
            score = max(score, 0.9)
        if score >= _SUGGESTION_THRESHOLD:
            scored.append((score, entry.name.casefold(), entry))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(entry for _, _, entry in scored[:limit])


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0


__all__ = [
    "InstalledInfo",
    "PluginCatalog",
    "PluginCatalogEntry",
    "PluginCatalogError",
    "PluginKind",
    "SASE_PLUGIN_ORG",
    "find_plugin",
    "load_plugin_catalog",
    "suggest_plugins",
]

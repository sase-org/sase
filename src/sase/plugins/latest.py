"""Latest-version enrichment for the SASE plugin catalog."""

from __future__ import annotations

import dataclasses
import importlib.metadata
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from packaging.version import InvalidVersion, Version

from sase.plugins.latest_cache import (
    CachedLatest,
    is_fresh,
    read_cache,
    write_cache,
)
from sase.plugins.pypi_source import fetch_latest_version
from sase.version._utils import normalize_distribution_name

if TYPE_CHECKING:
    from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry

LatestSource = Literal["index", "git", "editable", "unknown"]

FetchLatestFn = Callable[[str], str | None]
ReadLatestCacheFn = Callable[[], dict[str, CachedLatest]]
WriteLatestCacheFn = Callable[[dict[str, CachedLatest]], None]
ClockFn = Callable[[], float]
InstalledSourceFn = Callable[[str], LatestSource]

_MAX_WORKERS = 8


@dataclass(frozen=True)
class LatestInfo:
    """Latest available version metadata for one catalog plugin."""

    checked: bool = False
    version: str | None = None
    source: LatestSource = "unknown"
    error: str | None = None

    @classmethod
    def unknown(cls) -> LatestInfo:
        return cls()


def _installed_source(
    dist_name: str,
    *,
    distribution_fn: Callable[[str], Any] = importlib.metadata.distribution,
) -> LatestSource:
    """Classify an installed distribution using PEP 610 ``direct_url.json``."""
    try:
        distribution = distribution_fn(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return "index"
    except Exception:  # noqa: BLE001 - source display must never crash list/show.
        return "index"

    try:
        raw = distribution.read_text("direct_url.json")
    except Exception:  # noqa: BLE001 - malformed metadata degrades to index.
        return "index"
    if not raw:
        return "index"

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return "index"
    if not isinstance(payload, dict):
        return "index"

    dir_info = payload.get("dir_info")
    if isinstance(dir_info, dict) and dir_info.get("editable") is True:
        return "editable"
    vcs_info = payload.get("vcs_info")
    if isinstance(vcs_info, dict):
        return "git"
    return "index"


installed_source = _installed_source


def is_newer(latest: str | None, installed: str | None) -> bool:
    """Return whether *latest* is newer than *installed* using PEP 440 rules."""
    if not latest or not installed:
        return False
    try:
        return Version(latest) > Version(installed)
    except InvalidVersion:
        return False


def enrich_with_latest(
    catalog: PluginCatalog,
    *,
    offline: bool = False,
    refresh: bool = False,
    fetch_fn: FetchLatestFn = fetch_latest_version,
    read_cache_fn: ReadLatestCacheFn = read_cache,
    write_cache_fn: WriteLatestCacheFn = write_cache,
    clock: ClockFn = time.time,
    installed_source_fn: InstalledSourceFn | None = None,
    max_workers: int = _MAX_WORKERS,
) -> PluginCatalog:
    """Return *catalog* with latest-version metadata attached to every entry."""
    now = clock()
    installed_source_fn = (
        _installed_source if installed_source_fn is None else installed_source_fn
    )
    cached = {} if refresh and not offline else _safe_read_cache(read_cache_fn)
    resolved: dict[str, LatestInfo] = {}
    misses: dict[str, str] = {}

    for entry in catalog.entries:
        key = _cache_key(entry)
        if not key:
            continue
        source = _source_for_entry(entry, key, installed_source_fn)
        if source in {"editable", "git"}:
            resolved[key] = LatestInfo(
                checked=True,
                source=source,
                error="non-index install",
            )
            continue

        cached_entry = cached.get(key)
        if cached_entry is not None and is_fresh(cached_entry, now):
            resolved[key] = LatestInfo(
                checked=True,
                version=cached_entry.version,
                source="index",
                error=None if cached_entry.version else "unavailable",
            )
            continue

        if offline:
            resolved[key] = LatestInfo(
                checked=True,
                source="unknown",
                error="offline",
            )
            continue

        misses[key] = _dist_name(entry)

    if misses:
        fetched = _fetch_misses(misses, fetch_fn=fetch_fn, max_workers=max_workers)
        updated_cache = dict(cached)
        for key, version in fetched.items():
            updated_cache[key] = CachedLatest(version=version, fetched_at=now)
            resolved[key] = LatestInfo(
                checked=True,
                version=version,
                source="index",
                error=None if version else "unavailable",
            )
        _safe_write_cache(write_cache_fn, updated_cache)

    entries = tuple(
        dataclasses.replace(
            entry, latest=resolved.get(_cache_key(entry), LatestInfo.unknown())
        )
        for entry in catalog.entries
    )
    return dataclasses.replace(catalog, entries=entries)


def _safe_read_cache(read_cache_fn: ReadLatestCacheFn) -> dict[str, CachedLatest]:
    try:
        return read_cache_fn()
    except Exception:  # noqa: BLE001 - update hints should never break list/show.
        return {}


def _safe_write_cache(
    write_cache_fn: WriteLatestCacheFn,
    entries: dict[str, CachedLatest],
) -> None:
    try:
        write_cache_fn(entries)
    except Exception:  # noqa: BLE001 - cache writes are best effort.
        return


def _fetch_misses(
    misses: dict[str, str],
    *,
    fetch_fn: FetchLatestFn,
    max_workers: int,
) -> dict[str, str | None]:
    workers = max(1, min(max_workers, len(misses)))
    if workers == 1:
        return {key: _safe_fetch(dist, fetch_fn) for key, dist in misses.items()}

    results: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_safe_fetch, dist, fetch_fn): key
            for key, dist in misses.items()
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results


def _safe_fetch(dist_name: str, fetch_fn: FetchLatestFn) -> str | None:
    try:
        return fetch_fn(dist_name)
    except Exception:  # noqa: BLE001 - one failed lookup must not sink the batch.
        return None


def _source_for_entry(
    entry: PluginCatalogEntry,
    key: str,
    installed_source_fn: InstalledSourceFn,
) -> LatestSource:
    if not entry.installed.installed:
        return "index"
    return installed_source_fn(key)


def _cache_key(entry: PluginCatalogEntry) -> str:
    return normalize_distribution_name(_dist_name(entry))


def _dist_name(entry: PluginCatalogEntry) -> str:
    return entry.repo or entry.name


__all__ = [
    "FetchLatestFn",
    "InstalledSourceFn",
    "LatestInfo",
    "LatestSource",
    "enrich_with_latest",
    "installed_source",
    "is_newer",
]

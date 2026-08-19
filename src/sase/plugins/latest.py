"""Latest-version enrichment for the SASE plugin catalog."""

from __future__ import annotations

import dataclasses
import importlib.metadata
import json
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from sase.dev_update.detect import detect_dev_latest
from sase.dev_update.models import DevLatest
from sase.feature_flags import FeatureFlag, current_flags
from sase.plugins.latest_cache import (
    CachedLatest,
    is_fresh,
    prune_latest_cache,
    read_cache,
    write_cache,
)
from sase.plugins.pypi_source import fetch_latest_version
from sase.version._utils import normalize_distribution_name
from sase.version.inventory import (
    VersionPackageRecord,
    collect_runtime_version_inventory,
)

if TYPE_CHECKING:
    from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry

LatestSource = Literal["index", "git", "editable", "unknown"]
EagerScope = Literal["all", "installed"]

FetchLatestFn = Callable[[str], str | None]
ReadLatestCacheFn = Callable[[], dict[str, CachedLatest]]
WriteLatestCacheFn = Callable[[dict[str, CachedLatest]], None]
ClockFn = Callable[[], float]
InstalledSourceFn = Callable[[str], LatestSource]
VersionRecordsFn = Callable[[], Sequence[VersionPackageRecord]]


class _DetectDevLatestFn(Protocol):
    def __call__(self, record: VersionPackageRecord, *, offline: bool) -> DevLatest:
        """Return latest-dev metadata for one editable package."""
        ...


_MAX_WORKERS = 8
_FETCH_DEADLINE_SECONDS = 8.0


@dataclass(frozen=True)
class LatestInfo:
    """Latest available version metadata for one catalog plugin."""

    checked: bool = False
    version: str | None = None
    source: LatestSource = "unknown"
    error: str | None = None
    install_type: str | None = None
    current_version: str | None = None
    update_available: bool = False
    state: str | None = None
    reason: str | None = None
    git_root: str | None = None
    upstream_ref: str | None = None

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
    """Return whether *latest* is newer than *installed* using PEP 440 rules.

    ``packaging`` is imported lazily so that a stale editable tool environment
    that predates the dependency can still import this module and run the
    read-only catalog commands. When ``packaging`` is unavailable we degrade to
    ``False`` rather than claiming an update without a valid PEP 440 comparison.
    """
    if not latest or not installed:
        return False
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return False
    try:
        return Version(latest) > Version(installed)
    except InvalidVersion:
        return False


def _runtime_version_records() -> Sequence[VersionPackageRecord]:
    return collect_runtime_version_inventory(include_plugins=True).packages


def latest_cache_key(entry: PluginCatalogEntry) -> str:
    """Return the latest-version cache key for *entry*."""
    return _cache_key(entry)


def enrich_entry_latest(
    entry: PluginCatalogEntry,
    *,
    offline: bool = False,
    refresh: bool = False,
    fetch_fn: FetchLatestFn = fetch_latest_version,
    read_cache_fn: ReadLatestCacheFn = read_cache,
    write_cache_fn: WriteLatestCacheFn = write_cache,
    clock: ClockFn = time.time,
    installed_source_fn: InstalledSourceFn | None = None,
    version_records_fn: VersionRecordsFn | None = _runtime_version_records,
    detect_dev_latest_fn: _DetectDevLatestFn = detect_dev_latest,
    max_workers: int = 1,
    deadline_seconds: float | None = _FETCH_DEADLINE_SECONDS,
    monotonic: ClockFn = time.monotonic,
) -> PluginCatalogEntry:
    """Return *entry* with latest-version metadata attached.

    Used by the Updates pane's lazy highlighted-row fetch. Always eager for
    this single entry, independent of :class:`FeatureFlag.plugin_catalog_scoped_latest`.
    """
    from sase.plugins.catalog import PluginCatalog

    catalog = PluginCatalog(
        fetched_at=0.0,
        entries=(entry,),
        from_cache=True,
        stale=False,
    )
    enriched = enrich_with_latest(
        catalog,
        offline=offline,
        refresh=refresh,
        fetch_fn=fetch_fn,
        read_cache_fn=read_cache_fn,
        write_cache_fn=write_cache_fn,
        clock=clock,
        installed_source_fn=installed_source_fn,
        version_records_fn=version_records_fn,
        detect_dev_latest_fn=detect_dev_latest_fn,
        max_workers=max_workers,
        scope="all",
        deadline_seconds=deadline_seconds,
        monotonic=monotonic,
    )
    return enriched.entries[0]


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
    version_records_fn: VersionRecordsFn | None = _runtime_version_records,
    detect_dev_latest_fn: _DetectDevLatestFn = detect_dev_latest,
    max_workers: int = _MAX_WORKERS,
    scope: EagerScope | None = None,
    include_keys: Sequence[str] = (),
    deadline_seconds: float | None = _FETCH_DEADLINE_SECONDS,
    monotonic: ClockFn = time.monotonic,
) -> PluginCatalog:
    """Return *catalog* with latest-version metadata attached to entries.

    When *scope* is ``None``, :class:`FeatureFlag.plugin_catalog_scoped_latest`
    chooses between eager enrichment of every entry (``"all"``, the pre-scale
    default) and installed entries only (``"installed"``). *include_keys*
    always join the eager set so ``sase plugin show`` can fetch one uninstalled
    plugin without a catalog-wide network storm. Refresh force-expires entries
    in that eager set instead of discarding the whole cache.
    """
    now = clock()
    installed_source_fn = (
        _installed_source if installed_source_fn is None else installed_source_fn
    )
    eager_scope = _resolve_eager_scope(scope)
    include = {normalize_distribution_name(key) for key in include_keys if key} - {""}
    cached = _safe_read_cache(read_cache_fn)
    resolved: dict[str, LatestInfo] = {}
    misses: dict[str, str] = {}
    records = _record_lookup(_safe_version_records(version_records_fn))
    installed_versions = {
        key: entry.installed.version
        for entry in catalog.entries
        if (key := _cache_key(entry))
    }

    for entry in catalog.entries:
        key = _cache_key(entry)
        if not key:
            continue
        record = _record_for_entry(entry, records)
        source = _source_for_entry(entry, key, installed_source_fn, record)
        if source == "editable":
            resolved[key] = _editable_latest_info(
                entry,
                record=record,
                offline=offline,
                detect_dev_latest_fn=detect_dev_latest_fn,
            )
            continue
        if source == "git":
            resolved[key] = LatestInfo(
                checked=True,
                source=source,
                error="non-index install",
                install_type=source,
                current_version=entry.installed.version,
            )
            continue
        if not _is_eager_entry(entry, key, scope=eager_scope, include=include):
            continue

        cached_entry = cached.get(key)
        if not refresh and cached_entry is not None and is_fresh(cached_entry, now):
            resolved[key] = LatestInfo(
                checked=True,
                version=cached_entry.version,
                source="index",
                error=None if cached_entry.version else "unavailable",
                install_type=_install_type(record, "index"),
                current_version=entry.installed.version,
            )
            continue

        if offline:
            resolved[key] = LatestInfo(
                checked=True,
                source="unknown",
                error="offline",
                install_type=_install_type(record, None),
                current_version=entry.installed.version,
            )
            continue

        misses[key] = _dist_name(entry)

    if misses:
        fetched = _fetch_misses(
            misses,
            fetch_fn=fetch_fn,
            max_workers=max_workers,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        updated_cache = dict(cached)
        for key, version in fetched.items():
            updated_cache[key] = CachedLatest(version=version, fetched_at=now)
            resolved[key] = LatestInfo(
                checked=True,
                version=version,
                source="index",
                error=None if version else "unavailable",
                install_type=_install_type(records.get(key), "index"),
                current_version=installed_versions.get(key),
            )
        _safe_write_cache(write_cache_fn, prune_latest_cache(updated_cache, now))

    entries = tuple(
        dataclasses.replace(
            entry, latest=resolved.get(_cache_key(entry), LatestInfo.unknown())
        )
        for entry in catalog.entries
    )
    return dataclasses.replace(catalog, entries=entries)


def _resolve_eager_scope(scope: EagerScope | None) -> EagerScope:
    if scope is not None:
        return scope
    if current_flags().enabled(FeatureFlag.plugin_catalog_scoped_latest):
        return "installed"
    return "all"


def _is_eager_entry(
    entry: PluginCatalogEntry,
    key: str,
    *,
    scope: EagerScope,
    include: set[str],
) -> bool:
    if scope == "all" or key in include:
        return True
    return entry.installed.installed


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


def _safe_version_records(
    version_records_fn: VersionRecordsFn | None,
) -> Sequence[VersionPackageRecord]:
    if version_records_fn is None:
        return ()
    try:
        result = version_records_fn()
    except Exception:  # noqa: BLE001 - update hints should never break list/show.
        return ()
    if hasattr(result, "packages"):
        return tuple(result.packages)
    return result


def _record_lookup(
    records: Sequence[VersionPackageRecord],
) -> dict[str, VersionPackageRecord]:
    lookup: dict[str, VersionPackageRecord] = {}
    for record in records:
        if record.role != "plugin":
            continue
        key = normalize_distribution_name(record.name)
        if key:
            lookup[key] = record
    return lookup


def _record_for_entry(
    entry: PluginCatalogEntry,
    records: dict[str, VersionPackageRecord],
) -> VersionPackageRecord | None:
    for candidate in _record_name_candidates(entry):
        key = normalize_distribution_name(candidate)
        if not key:
            continue
        record = records.get(key)
        if record is not None:
            return record
    return None


def _record_name_candidates(entry: PluginCatalogEntry) -> tuple[str, ...]:
    candidates: list[str] = []
    if entry.repo:
        candidates.append(entry.repo)
        if not entry.repo.lower().startswith("sase-"):
            candidates.append(f"sase-{entry.repo}")
    if entry.name:
        candidates.append(entry.name)
        candidates.append(f"sase-{entry.name}")
    return tuple(_dedupe(candidates))


def _editable_latest_info(
    entry: PluginCatalogEntry,
    *,
    record: VersionPackageRecord | None,
    offline: bool,
    detect_dev_latest_fn: _DetectDevLatestFn,
) -> LatestInfo:
    if record is None:
        return LatestInfo(
            checked=True,
            source="editable",
            error="editable install is missing from version inventory",
            install_type="editable",
            current_version=entry.installed.version,
            state="unavailable",
            reason="editable install is missing from version inventory",
        )
    try:
        latest = detect_dev_latest_fn(record, offline=offline)
    except Exception as exc:  # noqa: BLE001 - display must never crash list/show.
        reason = f"dev version unavailable: {exc}"
        return LatestInfo(
            checked=True,
            source="editable",
            error=reason,
            install_type=record.install_type,
            current_version=record.display_version,
            state="unavailable",
            reason=reason,
        )
    return LatestInfo(
        checked=True,
        version=latest.latest_version,
        source="editable",
        error=_dev_error(latest),
        install_type=record.install_type,
        current_version=latest.current_version,
        update_available=latest.update_available,
        state=latest.state,
        reason=latest.reason,
        git_root=latest.git_root,
        upstream_ref=latest.upstream,
    )


def _dev_error(latest: DevLatest) -> str | None:
    if latest.state == "fetch_failed":
        return latest.fetch_error or latest.reason
    if latest.state == "unavailable":
        return latest.reason
    return None


def _fetch_misses(
    misses: dict[str, str],
    *,
    fetch_fn: FetchLatestFn,
    max_workers: int,
    deadline_seconds: float | None = _FETCH_DEADLINE_SECONDS,
    monotonic: ClockFn = time.monotonic,
) -> dict[str, str | None]:
    if not misses:
        return {}
    started = monotonic()
    workers = max(1, min(max_workers, len(misses)))

    def remaining() -> float | None:
        if deadline_seconds is None:
            return None
        return max(0.0, deadline_seconds - (monotonic() - started))

    if workers == 1:
        results: dict[str, str | None] = {}
        for key, dist in misses.items():
            left = remaining()
            if left is not None and left <= 0:
                results[key] = None
                continue
            results[key] = _safe_fetch(dist, fetch_fn)
        return results

    results = {}
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {
            executor.submit(_safe_fetch, dist, fetch_fn): key
            for key, dist in misses.items()
        }
        pending = set(futures)
        while pending:
            left = remaining()
            if left is not None and left <= 0:
                for future in pending:
                    future.cancel()
                    results[futures[future]] = None
                break
            done, pending = wait(
                pending,
                timeout=left,
                return_when=FIRST_COMPLETED,
            )
            if not done and left is not None:
                for future in pending:
                    future.cancel()
                    results[futures[future]] = None
                break
            for future in done:
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception:  # noqa: BLE001 - one failed lookup must not sink the batch.
                    results[key] = None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    for key in misses:
        results.setdefault(key, None)
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
    record: VersionPackageRecord | None,
) -> LatestSource:
    if not entry.installed.installed:
        return "index"
    if record is not None:
        if record.install_type == "editable":
            return "editable"
        if record.install_type == "wheel":
            return "index"
    return installed_source_fn(key)


def _cache_key(entry: PluginCatalogEntry) -> str:
    return normalize_distribution_name(_dist_name(entry))


def _dist_name(entry: PluginCatalogEntry) -> str:
    return entry.repo or entry.name


def _install_type(
    record: VersionPackageRecord | None, fallback: str | None
) -> str | None:
    if record is not None:
        return record.install_type
    return fallback


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(value)
    return tuple(result)


__all__ = [
    "EagerScope",
    "FetchLatestFn",
    "InstalledSourceFn",
    "LatestInfo",
    "LatestSource",
    "VersionRecordsFn",
    "enrich_entry_latest",
    "enrich_with_latest",
    "installed_source",
    "is_newer",
    "latest_cache_key",
]

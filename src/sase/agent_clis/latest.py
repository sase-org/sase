"""Latest-version oracles (npm registry, JSON endpoint) with a TTL cache."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from sase.core.paths import ensure_sase_directory, sase_subdir

SCHEMA_VERSION = 2
CACHE_SUBDIR = "agent_clis"
CACHE_FILENAME = "latest_cache.json"
LATEST_TTL_SECONDS = 6 * 60 * 60
REGISTRY_TIMEOUT_SECONDS = 5.0


class _Response(Protocol):
    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


UrlOpenFn = Callable[..., _Response]
FetchFn = Callable[["LatestQuery"], str | None]
ReadCacheFn = Callable[[], dict[str, "CachedLatest"]]
WriteCacheFn = Callable[[dict[str, "CachedLatest"]], None]
ClockFn = Callable[[], float]

LatestKind = Literal["npm", "url"]
DEFAULT_JSON_FIELD = "version"


@dataclass(frozen=True)
class LatestQuery:
    """One latest-version lookup: where to ask, and how to key the answer."""

    key: str
    kind: LatestKind
    target: str
    field: str = DEFAULT_JSON_FIELD

    @classmethod
    def for_npm(cls, package: str) -> LatestQuery:
        return cls(key=f"npm:{package}", kind="npm", target=package)

    @classmethod
    def for_url(cls, url: str, *, field: str = DEFAULT_JSON_FIELD) -> LatestQuery:
        return cls(key=f"url:{url}", kind="url", target=url, field=field)


@dataclass(frozen=True)
class CachedLatest:
    version: str | None
    fetched_at: float


@dataclass(frozen=True)
class LatestVersion:
    version: str | None
    error: str | None = None
    cached: bool = False


def _cache_path() -> Path:
    return sase_subdir(CACHE_SUBDIR) / CACHE_FILENAME


def _fetch_npm_latest_version(
    package: str,
    *,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = REGISTRY_TIMEOUT_SECONDS,
) -> str | None:
    """Fetch the npm ``latest`` dist-tag version for *package*."""
    encoded = urllib.parse.quote(package, safe="")
    request = urllib.request.Request(
        f"https://registry.npmjs.org/{encoded}/latest",
        headers={"Accept": "application/json", "User-Agent": "sase-agent-cli"},
    )
    try:
        with urlopen_fn(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    return version.strip() if isinstance(version, str) and version.strip() else None


def _fetch_url_latest_version(
    url: str,
    *,
    field: str = DEFAULT_JSON_FIELD,
    urlopen_fn: UrlOpenFn = urllib.request.urlopen,
    timeout: float = REGISTRY_TIMEOUT_SECONDS,
) -> str | None:
    """Fetch a version string from *field* of an HTTPS JSON endpoint."""
    if not url.startswith("https://"):
        return None
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "sase-agent-cli"},
    )
    try:
        with urlopen_fn(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get(field)
    return version.strip() if isinstance(version, str) and version.strip() else None


def _fetch_latest_version(query: LatestQuery) -> str | None:
    """Dispatch one query to the oracle that serves its ``kind``."""
    if query.kind == "url":
        return _fetch_url_latest_version(query.target, field=query.field)
    return _fetch_npm_latest_version(query.target)


def read_cache(path: Path | None = None) -> dict[str, CachedLatest]:
    """Read cached latest versions; malformed entries are ignored."""
    try:
        envelope = json.loads((path or _cache_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(envelope, dict)
        or envelope.get("schema_version") != SCHEMA_VERSION
    ):
        return {}
    raw_entries = envelope.get("entries")
    if not isinstance(raw_entries, dict):
        return {}
    entries: dict[str, CachedLatest] = {}
    for key, raw in raw_entries.items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            continue
        version = raw.get("version")
        fetched_at = raw.get("fetched_at")
        if version is not None and not isinstance(version, str):
            continue
        if not isinstance(fetched_at, int | float) or isinstance(fetched_at, bool):
            continue
        entries[key] = CachedLatest(version, float(fetched_at))
    return entries


def write_cache(entries: dict[str, CachedLatest], *, path: Path | None = None) -> None:
    """Atomically persist latest-version entries."""
    cache_path = path or _cache_path()
    if path is None:
        ensure_sase_directory(CACHE_SUBDIR)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "entries": {
            key: {"version": item.version, "fetched_at": item.fetched_at}
            for key, item in sorted(entries.items())
        },
    }
    tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(tmp_path, cache_path)


def is_fresh(
    item: CachedLatest,
    now: float,
    *,
    ttl_seconds: float = LATEST_TTL_SECONDS,
) -> bool:
    age = now - item.fetched_at
    return 0 <= age < ttl_seconds


def get_latest_versions(
    queries: Iterable[LatestQuery | str],
    *,
    offline: bool = False,
    refresh: bool = False,
    ttl_seconds: float = LATEST_TTL_SECONDS,
    fetch_fn: FetchFn = _fetch_latest_version,
    read_cache_fn: ReadCacheFn = read_cache,
    write_cache_fn: WriteCacheFn = write_cache,
    clock: ClockFn = time.time,
) -> dict[str, LatestVersion]:
    """Resolve each query from fresh cache or its remote oracle.

    Results and cache entries are keyed by ``LatestQuery.key``, so npm
    packages and JSON endpoints share one TTL cache without colliding. Bare
    strings are accepted as npm packages. Offline mode never fetches. A stale
    cached value remains useful offline and is returned with an
    ``offline_stale_cache`` marker.
    """
    unique = tuple(
        {
            query.key: query
            for query in (
                item if isinstance(item, LatestQuery) else LatestQuery.for_npm(item)
                for item in queries
                if item
            )
        }.values()
    )
    now = clock()
    try:
        cached = read_cache_fn()
    except Exception:  # noqa: BLE001 - latest hints are best effort.
        cached = {}
    results: dict[str, LatestVersion] = {}
    updated_cache = dict(cached)
    cache_changed = False

    for query in unique:
        key = query.key
        item = cached.get(key)
        if (
            item is not None
            and not refresh
            and is_fresh(item, now, ttl_seconds=ttl_seconds)
        ):
            results[key] = LatestVersion(item.version, cached=True)
            continue
        if offline:
            if item is None:
                results[key] = LatestVersion(None, error="offline")
            else:
                results[key] = LatestVersion(
                    item.version, error="offline_stale_cache", cached=True
                )
            continue
        try:
            version = fetch_fn(query)
        except Exception:  # noqa: BLE001 - network errors degrade to unknown.
            version = None
        if version is None and item is not None:
            results[key] = LatestVersion(
                item.version, error="registry_unavailable", cached=True
            )
            continue
        error = None if version is not None else "registry_unavailable"
        results[key] = LatestVersion(version, error=error)
        updated_cache[key] = CachedLatest(version, now)
        cache_changed = True

    if cache_changed:
        try:
            write_cache_fn(updated_cache)
        except Exception:  # noqa: BLE001 - cache writes are best effort.
            pass
    return results


__all__ = [
    "CACHE_FILENAME",
    "CACHE_SUBDIR",
    "DEFAULT_JSON_FIELD",
    "LATEST_TTL_SECONDS",
    "CachedLatest",
    "LatestQuery",
    "LatestVersion",
    "get_latest_versions",
    "is_fresh",
    "read_cache",
    "write_cache",
]

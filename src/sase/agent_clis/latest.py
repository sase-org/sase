"""Npm-registry latest-version oracle with a tolerant TTL cache."""

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
from typing import Any, Protocol

from sase.core.paths import ensure_sase_directory, sase_subdir

SCHEMA_VERSION = 1
CACHE_SUBDIR = "agent_clis"
CACHE_FILENAME = "latest_cache.json"
LATEST_TTL_SECONDS = 6 * 60 * 60
REGISTRY_TIMEOUT_SECONDS = 5.0


class _Response(Protocol):
    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


UrlOpenFn = Callable[..., _Response]
FetchFn = Callable[[str], str | None]
ReadCacheFn = Callable[[], dict[str, "CachedLatest"]]
WriteCacheFn = Callable[[dict[str, "CachedLatest"]], None]
ClockFn = Callable[[], float]


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


def read_cache(path: Path | None = None) -> dict[str, CachedLatest]:
    """Read cached npm versions; malformed entries are ignored."""
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
    for package, raw in raw_entries.items():
        if not isinstance(package, str) or not isinstance(raw, dict):
            continue
        version = raw.get("version")
        fetched_at = raw.get("fetched_at")
        if version is not None and not isinstance(version, str):
            continue
        if not isinstance(fetched_at, int | float) or isinstance(fetched_at, bool):
            continue
        entries[package] = CachedLatest(version, float(fetched_at))
    return entries


def write_cache(entries: dict[str, CachedLatest], *, path: Path | None = None) -> None:
    """Atomically persist npm latest-version entries."""
    cache_path = path or _cache_path()
    if path is None:
        ensure_sase_directory(CACHE_SUBDIR)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "entries": {
            package: {"version": item.version, "fetched_at": item.fetched_at}
            for package, item in sorted(entries.items())
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
    packages: Iterable[str],
    *,
    offline: bool = False,
    refresh: bool = False,
    ttl_seconds: float = LATEST_TTL_SECONDS,
    fetch_fn: FetchFn = _fetch_npm_latest_version,
    read_cache_fn: ReadCacheFn = read_cache,
    write_cache_fn: WriteCacheFn = write_cache,
    clock: ClockFn = time.time,
) -> dict[str, LatestVersion]:
    """Resolve each package from fresh cache or the npm registry.

    Offline mode never fetches. A stale cached value remains useful offline and
    is returned with an ``offline_stale_cache`` marker.
    """
    unique = tuple(dict.fromkeys(package for package in packages if package))
    now = clock()
    try:
        cached = read_cache_fn()
    except Exception:  # noqa: BLE001 - latest hints are best effort.
        cached = {}
    results: dict[str, LatestVersion] = {}
    updated_cache = dict(cached)
    cache_changed = False

    for package in unique:
        item = cached.get(package)
        if (
            item is not None
            and not refresh
            and is_fresh(item, now, ttl_seconds=ttl_seconds)
        ):
            results[package] = LatestVersion(item.version, cached=True)
            continue
        if offline:
            if item is None:
                results[package] = LatestVersion(None, error="offline")
            else:
                results[package] = LatestVersion(
                    item.version, error="offline_stale_cache", cached=True
                )
            continue
        try:
            version = fetch_fn(package)
        except Exception:  # noqa: BLE001 - network errors degrade to unknown.
            version = None
        if version is None and item is not None:
            results[package] = LatestVersion(
                item.version, error="registry_unavailable", cached=True
            )
            continue
        error = None if version is not None else "registry_unavailable"
        results[package] = LatestVersion(version, error=error)
        updated_cache[package] = CachedLatest(version, now)
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
    "LATEST_TTL_SECONDS",
    "CachedLatest",
    "LatestVersion",
    "get_latest_versions",
    "is_fresh",
    "read_cache",
    "write_cache",
]

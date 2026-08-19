"""Short-TTL cache for latest plugin versions from PyPI."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.version._utils import normalize_distribution_name

SCHEMA_VERSION = 1
CACHE_SUBDIR = "plugins"
CACHE_FILENAME = "latest_cache.json"
LATEST_TTL_SECONDS = 6 * 60 * 60
LATEST_CACHE_MAX_AGE_SECONDS = LATEST_TTL_SECONDS * 4


@dataclass(frozen=True)
class CachedLatest:
    """A cached latest-version probe result for one distribution."""

    version: str | None
    fetched_at: float


def _cache_path() -> Path:
    return sase_subdir(CACHE_SUBDIR) / CACHE_FILENAME


def read_cache(path: Path | None = None) -> dict[str, CachedLatest]:
    """Read the latest-version cache, returning an empty mapping on failure."""
    cache_path = path or _cache_path()
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(envelope, dict):
        return {}
    if envelope.get("schema_version") != SCHEMA_VERSION:
        return {}

    raw_entries = envelope.get("entries")
    if not isinstance(raw_entries, dict):
        return {}

    entries: dict[str, CachedLatest] = {}
    for raw_name, raw_entry in raw_entries.items():
        if not isinstance(raw_name, str) or not isinstance(raw_entry, dict):
            continue
        key = normalize_distribution_name(raw_name)
        if not key:
            continue
        version = raw_entry.get("version")
        if version is not None and not isinstance(version, str):
            continue
        fetched_at = raw_entry.get("fetched_at")
        if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
            continue
        entries[key] = CachedLatest(version=version, fetched_at=float(fetched_at))
    return entries


def prune_latest_cache(
    entries: dict[str, CachedLatest],
    now: float,
    *,
    max_age_seconds: float = LATEST_CACHE_MAX_AGE_SECONDS,
) -> dict[str, CachedLatest]:
    """Drop cache rows older than *max_age_seconds* (a multiple of the TTL)."""
    return {
        key: cached
        for key, cached in entries.items()
        if now - cached.fetched_at < max_age_seconds
    }


def write_cache(
    entries: dict[str, CachedLatest],
    *,
    path: Path | None = None,
    now: float | None = None,
    max_age_seconds: float = LATEST_CACHE_MAX_AGE_SECONDS,
) -> None:
    """Atomically write *entries* to the latest-version cache.

    Stale rows older than :data:`LATEST_CACHE_MAX_AGE_SECONDS` are evicted on
    every write so the file cannot grow without bound.
    """
    cache_path = path or _cache_path()
    if path is None:
        ensure_sase_directory(CACHE_SUBDIR)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

    pruned = prune_latest_cache(
        entries,
        time.time() if now is None else now,
        max_age_seconds=max_age_seconds,
    )
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "entries": {
            normalize_distribution_name(name): {
                "version": cached.version,
                "fetched_at": cached.fetched_at,
            }
            for name, cached in sorted(pruned.items())
            if normalize_distribution_name(name)
        },
    }
    serialized = json.dumps(envelope, indent=2, sort_keys=True)

    tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    os.replace(tmp_path, cache_path)


def is_fresh(
    cached: CachedLatest,
    now: float,
    *,
    ttl_seconds: float = LATEST_TTL_SECONDS,
) -> bool:
    """Return ``True`` when *cached* is still inside the latest-version TTL."""
    return now - cached.fetched_at < ttl_seconds


__all__ = [
    "CACHE_FILENAME",
    "CACHE_SUBDIR",
    "LATEST_CACHE_MAX_AGE_SECONDS",
    "LATEST_TTL_SECONDS",
    "CachedLatest",
    "SCHEMA_VERSION",
    "is_fresh",
    "prune_latest_cache",
    "read_cache",
    "write_cache",
]

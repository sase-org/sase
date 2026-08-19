"""On-disk cache for the SASE plugin catalog.

The catalog is fetched from GitHub once and cached at
``~/.sase/plugins/catalog_cache.json`` so the ``sase plugin`` commands are
instant on repeat runs and never make a surprise network call. Only the
GitHub-derived entry payloads are cached; installed status is recomputed from
the live environment on every load (see :mod:`sase.plugins.catalog`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import ensure_sase_directory, sase_subdir

#: Bump when the cached envelope shape changes incompatibly.
SCHEMA_VERSION = 1

#: Subdirectory under ``sase_home()`` that holds the catalog cache.
CACHE_SUBDIR = "plugins"

#: Cache file name under the plugins subdirectory.
CACHE_FILENAME = "catalog_cache.json"

#: Soft staleness threshold (7 days). Past this the footer warns more loudly,
#: but loads still never auto-fetch — predictable latency beats surprise slowness.
CACHE_STALENESS_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class CachedCatalog:
    """A successfully-read cache envelope."""

    fetched_at: float
    query: str
    entries: tuple[dict[str, Any], ...]


def _cache_path() -> Path:
    """Return the catalog cache file path (does not create anything)."""
    return sase_subdir(CACHE_SUBDIR) / CACHE_FILENAME


def read_cache() -> CachedCatalog | None:
    """Read the cache envelope, or ``None`` if missing, unreadable, or stale-schema."""
    path = _cache_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("schema_version") != SCHEMA_VERSION:
        return None

    fetched_at = envelope.get("fetched_at")
    if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
        return None

    raw_entries = envelope.get("entries")
    if not isinstance(raw_entries, list):
        return None
    entries = tuple(entry for entry in raw_entries if isinstance(entry, dict))

    query = envelope.get("query")
    return CachedCatalog(
        fetched_at=float(fetched_at),
        query=query if isinstance(query, str) else "",
        entries=entries,
    )


def write_cache(
    entries: list[dict[str, Any]],
    *,
    fetched_at: float,
    query: str,
) -> None:
    """Atomically write the cache envelope (temp file + ``os.replace``)."""
    ensure_sase_directory(CACHE_SUBDIR)
    path = _cache_path()
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "fetched_at": fetched_at,
        "query": query,
        "entries": entries,
    }
    serialized = json.dumps(envelope, sort_keys=True, separators=(",", ":"))

    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    os.replace(tmp_path, path)


def cache_age_seconds(fetched_at: float, now: float) -> float:
    """Return the non-negative age of the cache in seconds."""
    return max(0.0, now - fetched_at)


def is_cache_stale(fetched_at: float, now: float) -> bool:
    """Return ``True`` when the cache is older than the soft staleness threshold."""
    return cache_age_seconds(fetched_at, now) >= CACHE_STALENESS_SECONDS


__all__ = [
    "CACHE_STALENESS_SECONDS",
    "CachedCatalog",
    "SCHEMA_VERSION",
    "cache_age_seconds",
    "is_cache_stale",
    "read_cache",
    "write_cache",
]

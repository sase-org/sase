"""Best-effort fetch freshness cache for ``sase stitch log``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from sase.core.paths import sase_home

SCHEMA_VERSION = 1
DEFAULT_FRESH_TTL_SECONDS = 60.0
DEFAULT_RETENTION_SECONDS = 7 * 24 * 60 * 60.0
_CACHE_FILENAME = "vcs_log_fetch_cache.json"


@dataclass(frozen=True)
class _FetchCacheEntry:
    """One successful fetch timestamp for one checkout/ref pair."""

    repo_path: str
    remote_ref: str
    fetched_at: float


def _default_cache_path() -> Path:
    """Return the default per-user fetch cache file."""
    return sase_home() / _CACHE_FILENAME


def _normalize_repo_path(repo_path: str | Path) -> str:
    """Return the checkout identity used by the fetch cache."""
    path = Path(repo_path).expanduser()
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return str(path.absolute())


def _fetch_cache_key(repo_path: str | Path, remote_ref: str) -> str:
    """Return a stable JSON-safe key for a checkout/ref pair."""
    identity = _normalize_repo_path(repo_path) + "\0" + remote_ref
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _read_fetch_cache(
    cache_path: str | Path | None = None,
) -> dict[str, _FetchCacheEntry]:
    """Read cache entries, treating absent or malformed files as empty."""
    path = _cache_path(cache_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _entries_from_payload(payload)


def _write_fetch_cache(
    entries: Mapping[str, _FetchCacheEntry],
    *,
    cache_path: str | Path | None = None,
    now: float | None = None,
    retention_seconds: float = DEFAULT_RETENTION_SECONDS,
) -> bool:
    """Atomically write cache entries, returning ``False`` on best-effort failure."""
    path = _cache_path(cache_path)
    timestamp = _now(now)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "entries": _entries_to_payload(
            entries,
            now=timestamp,
            retention_seconds=retention_seconds,
        ),
    }

    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=f".{os.getpid()}.tmp",
            dir=path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        return True
    except OSError:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        return False


def fresh_fetch_time(
    repo_path: str | Path,
    remote_ref: str,
    *,
    now: float | None = None,
    ttl_seconds: float = DEFAULT_FRESH_TTL_SECONDS,
    cache_path: str | Path | None = None,
) -> float | None:
    """Return the fresh cached fetch timestamp for a checkout/ref, if any."""
    timestamp = _now(now)
    entries = _read_fetch_cache(cache_path)
    entry = entries.get(_fetch_cache_key(repo_path, remote_ref))
    if entry is None:
        return None
    age = timestamp - entry.fetched_at
    if 0 <= age < ttl_seconds:
        return entry.fetched_at
    return None


def record_successful_fetch(
    repo_path: str | Path,
    remote_ref: str,
    *,
    fetched_at: float | None = None,
    cache_path: str | Path | None = None,
    retention_seconds: float = DEFAULT_RETENTION_SECONDS,
) -> bool:
    """Record a successful fetch timestamp for a checkout/ref pair."""
    timestamp = _now(fetched_at)
    normalized_path = _normalize_repo_path(repo_path)
    key = _fetch_cache_key(normalized_path, remote_ref)
    entries = _read_fetch_cache(cache_path)
    entries[key] = _FetchCacheEntry(
        repo_path=normalized_path,
        remote_ref=remote_ref,
        fetched_at=timestamp,
    )
    return _write_fetch_cache(
        entries,
        cache_path=cache_path,
        now=timestamp,
        retention_seconds=retention_seconds,
    )


def _cache_path(cache_path: str | Path | None) -> Path:
    return (
        Path(cache_path).expanduser()
        if cache_path is not None
        else _default_cache_path()
    )


def _now(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _entries_from_payload(payload: Any) -> dict[str, _FetchCacheEntry]:
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") != SCHEMA_VERSION:
        return {}
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        return {}

    entries: dict[str, _FetchCacheEntry] = {}
    for key, value in raw_entries.items():
        if not isinstance(key, str):
            continue
        entry = _entry_from_payload(value)
        if entry is None:
            continue
        entries[key] = entry
    return entries


def _entry_from_payload(value: Any) -> _FetchCacheEntry | None:
    if not isinstance(value, dict):
        return None
    repo_path = value.get("repo_path")
    remote_ref = value.get("remote_ref")
    fetched_at = value.get("fetched_at")
    if not isinstance(repo_path, str) or not repo_path:
        return None
    if not isinstance(remote_ref, str) or not remote_ref:
        return None
    if not isinstance(fetched_at, (int, float)):
        return None
    return _FetchCacheEntry(
        repo_path=repo_path,
        remote_ref=remote_ref,
        fetched_at=float(fetched_at),
    )


def _entries_to_payload(
    entries: Mapping[str, _FetchCacheEntry],
    *,
    now: float,
    retention_seconds: float,
) -> dict[str, dict[str, object]]:
    cutoff = now - retention_seconds
    payload: dict[str, dict[str, object]] = {}
    for key in sorted(entries):
        entry = entries[key]
        if entry.fetched_at < cutoff:
            continue
        payload[key] = {
            "repo_path": entry.repo_path,
            "remote_ref": entry.remote_ref,
            "fetched_at": entry.fetched_at,
        }
    return payload


__all__ = [
    "DEFAULT_FRESH_TTL_SECONDS",
    "DEFAULT_RETENTION_SECONDS",
    "fresh_fetch_time",
    "record_successful_fetch",
]

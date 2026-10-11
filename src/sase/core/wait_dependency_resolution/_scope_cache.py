"""Persistent scope-key cache for scoped wait-dependency views.

A live ``wait_checks`` tick (and every parked runner's 60 s fallback) selects
the artifact rows its named waiters can depend on through
:func:`sase.core.wait_dependency_resolution.artifact_scope_keys`. Computing
those keys needs each artifact's ``agent_meta.json``, so selection used to
cost one JSON read per artifact. This module persists the keys instead:
each entry is fingerprinted by its ``agent_meta.json`` ``stat`` data
(``st_mtime_ns``, ``st_size``, ``st_ino``), so a later tick pays one
``stat`` per artifact and only reads the metas it actually selects.

Contract (from plan ``202610/wait_checks_scoped_view.md``):

- Only ``wait_checks`` writes the cache, with a temp file plus
  ``os.replace``, and only when an entry changed.
- Runners read it read-only; on a miss they read the meta themselves and
  never write.
- An unreadable, corrupt, or wrong-schema cache is treated as empty, so
  everything is read. It is never treated as "no rows".
- Selected rows always read their meta fresh, so the cache can only affect
  **which** rows are selected, never their content. New artifact dirs are
  cache misses and still read meta, which preserves the confirmation pass's
  new-member signal.
- Deleting the cache file is always safe: the next tick rebuilds it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ._artifact_state import artifact_dir_key

#: Cache file schema version (bumped when the entry layout changes).
SCHEMA_VERSION = 1

#: Cache file name under ``sase_home() / "cache"``.
SCOPE_KEY_CACHE_FILENAME = "wait_scope_keys.json"

_Fingerprint = tuple[int, int, int]


@dataclass
class _CacheEntry:
    """One cached artifact's stat fingerprint plus its scope keys."""

    mtime_ns: int
    size: int
    ino: int
    keys: frozenset[str]

    def matches(self, fingerprint: _Fingerprint) -> bool:
        mtime_ns, size, ino = fingerprint
        return self.mtime_ns == mtime_ns and self.size == size and self.ino == ino


class ScopeKeyCache:
    """In-memory scope-key entries with change tracking for one tick."""

    def __init__(self, entries: dict[str, _CacheEntry] | None = None) -> None:
        self._entries: dict[str, _CacheEntry] = dict(entries or {})
        self._changed = False

    @classmethod
    def empty(cls) -> ScopeKeyCache:
        """Return a cache with no entries (a cold cache)."""
        return cls({})

    @classmethod
    def load(cls, path: Path | None = None) -> ScopeKeyCache:
        """Load the cache file, treating any problem as an empty cache.

        An unreadable, corrupt, or wrong-schema file yields an empty cache
        so callers fall back to reading every meta, never to "no rows".
        """
        raw = _read_cache_file(path or scope_cache_path())
        if raw is None:
            return cls.empty()
        return cls(raw)

    def lookup(
        self, artifact_dir: Path | str, fingerprint: _Fingerprint
    ) -> frozenset[str] | None:
        """Return cached keys on a fingerprint hit, else ``None``."""
        entry = self._entries.get(artifact_dir_key(str(artifact_dir)))
        if entry is not None and entry.matches(fingerprint):
            return entry.keys
        return None

    def store(
        self,
        artifact_dir: Path | str,
        fingerprint: _Fingerprint,
        keys: frozenset[str] | set[str],
    ) -> None:
        """Record *keys* for *artifact_dir*, marking the cache changed."""
        mtime_ns, size, ino = fingerprint
        frozen = frozenset(keys)
        key = artifact_dir_key(str(artifact_dir))
        existing = self._entries.get(key)
        if (
            existing is not None
            and existing.matches(fingerprint)
            and existing.keys == frozen
        ):
            return
        self._entries[key] = _CacheEntry(mtime_ns, size, ino, frozen)
        self._changed = True

    def drop(self, artifact_dir: Path | str) -> None:
        """Forget *artifact_dir*, marking the cache changed when present."""
        if self._entries.pop(artifact_dir_key(str(artifact_dir)), None) is not None:
            self._changed = True

    def drop_missing(self, present: Iterable[Path | str]) -> None:
        """Forget entries for artifact dirs not in *present*."""
        live = {artifact_dir_key(str(path)) for path in present}
        for key in [key for key in self._entries if key not in live]:
            del self._entries[key]
            self._changed = True

    @property
    def changed(self) -> bool:
        """Return whether any entry changed since load."""
        return self._changed

    def snapshot(self) -> dict[str, _CacheEntry]:
        """Return a copy of the entries (for tests)."""
        return dict(self._entries)

    def save_if_changed(self, path: Path | None = None) -> bool:
        """Write the cache file when an entry changed; return if written.

        The write is atomic (temp file plus ``os.replace``) and best-effort:
        an ``OSError`` yields ``False`` instead of raising, because a cache
        write must never fail a ``wait_checks`` tick.
        """
        if not self._changed:
            return False
        target = path or scope_cache_path()
        tmp: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.parent / f".tmp-{os.getpid()}-{id(self):x}.json"
            tmp.write_text(
                json.dumps(_serialize(self._entries), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, target)
        except OSError:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            return False
        self._changed = False
        return True


def scope_cache_path() -> Path:
    """Return the scope-key cache file under the SASE state home."""
    return sase_home() / "cache" / SCOPE_KEY_CACHE_FILENAME


def stat_agent_meta(artifact_dir: Path | str) -> _Fingerprint | None:
    """Return the ``agent_meta.json`` stat fingerprint, or ``None``.

    ``None`` covers a missing meta (no row, as today) and any stat failure.
    """
    try:
        stat = os.stat(Path(artifact_dir) / "agent_meta.json")
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def keys_for_artifact_dir(
    cache: ScopeKeyCache,
    artifact_dir: Path,
    *,
    read_meta: Callable[[Path], Mapping[str, Any] | None],
    update_cache: bool,
) -> frozenset[str] | None:
    """Return the scope keys for one artifact dir through *cache*.

    A fingerprint hit reuses the cached keys without reading the meta. A
    miss or new dir reads the meta, computes the keys, and — when
    *update_cache* holds (``wait_checks`` only) — stores the entry. A
    missing or unreadable meta yields ``None`` (no row) and drops any
    stale entry. Runners pass ``update_cache=False``: on a miss they read
    the meta themselves and never write.
    """
    from ._scope import artifact_scope_keys

    fingerprint = stat_agent_meta(artifact_dir)
    if fingerprint is None:
        cache.drop(artifact_dir)
        return None
    hit = cache.lookup(artifact_dir, fingerprint)
    if hit is not None:
        return hit
    meta = read_meta(artifact_dir)
    if meta is None:
        cache.drop(artifact_dir)
        return None
    keys = artifact_scope_keys(meta)
    if update_cache:
        cache.store(artifact_dir, fingerprint, keys)
    return keys


def select_dirs_with_cache(
    artifact_dirs: Iterable[Path],
    scope_keys: Iterable[str],
    *,
    include_dirs: Iterable[Path | str],
    cache: ScopeKeyCache,
    read_meta: Callable[[Path], Mapping[str, Any] | None],
    update_cache: bool,
) -> list[Path]:
    """Select dirs whose keys intersect *scope_keys* plus *include_dirs*.

    Mirrors :func:`sase.core.wait_dependency_resolution.select_scope_rows`
    but resolves per-dir keys through the cache, so unselected artifacts
    cost one ``stat`` instead of one JSON read. Dirs with a missing or
    unreadable meta are omitted (no row, as today), even when explicitly
    included. New dirs are cache misses and read meta, preserving the
    confirmation pass's new-member signal.
    """
    wanted = frozenset(scope_keys)
    included = {artifact_dir_key(str(path)) for path in include_dirs}
    selected: list[Path] = []
    for artifact_dir in artifact_dirs:
        if artifact_dir_key(str(artifact_dir)) in included:
            if stat_agent_meta(artifact_dir) is None:
                cache.drop(artifact_dir)
                continue
            selected.append(artifact_dir)
            continue
        keys = keys_for_artifact_dir(
            cache, artifact_dir, read_meta=read_meta, update_cache=update_cache
        )
        if keys is not None and not keys.isdisjoint(wanted):
            selected.append(artifact_dir)
    return selected


def _read_cache_file(path: Path) -> dict[str, _CacheEntry] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    parsed: dict[str, _CacheEntry] = {}
    for dir_key, entry in entries.items():
        if not isinstance(dir_key, str) or not isinstance(entry, dict):
            return None
        try:
            mtime_ns = entry["mtime_ns"]
            size = entry["size"]
            ino = entry["ino"]
            keys = entry["keys"]
        except KeyError:
            return None
        if (
            not isinstance(mtime_ns, int)
            or isinstance(mtime_ns, bool)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(ino, int)
            or isinstance(ino, bool)
            or not isinstance(keys, list)
            or not all(isinstance(key, str) for key in keys)
        ):
            return None
        parsed[dir_key] = _CacheEntry(mtime_ns, size, ino, frozenset(keys))
    return parsed


def _serialize(entries: dict[str, _CacheEntry]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": {
            dir_key: {
                "mtime_ns": entry.mtime_ns,
                "size": entry.size,
                "ino": entry.ino,
                "keys": sorted(entry.keys),
            }
            for dir_key, entry in entries.items()
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "SCOPE_KEY_CACHE_FILENAME",
    "ScopeKeyCache",
    "keys_for_artifact_dir",
    "scope_cache_path",
    "select_dirs_with_cache",
    "stat_agent_meta",
]

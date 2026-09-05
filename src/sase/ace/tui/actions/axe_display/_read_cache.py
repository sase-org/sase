"""Mtime/size keyed cache for immutable axe status reads."""

from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

T = TypeVar("T")

_MAX_JSON_ENTRIES = 4096
_MAX_TAIL_ENTRIES = 512

JsonKind = Literal["index", "run"]


@dataclasses.dataclass
class AxeCollectorStats:
    """Per-tick counters for axe status collection I/O."""

    run_index_reads: int = 0
    run_index_cache_hits: int = 0
    run_json_parses: int = 0
    run_json_cache_hits: int = 0
    log_tail_reads: int = 0
    log_tail_cache_hits: int = 0
    file_opens: int = 0


@dataclasses.dataclass(frozen=True)
class _FileIdentity:
    exists: bool
    mtime_ns: int
    size: int


def _stat_identity(path: Path) -> _FileIdentity | None:
    """Return path identity, or None when stat fails and the cache must fail open."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return _FileIdentity(exists=False, mtime_ns=0, size=0)
    except OSError:
        return None
    return _FileIdentity(exists=True, mtime_ns=st.st_mtime_ns, size=st.st_size)


class AxeStatusReadCache:
    """Reuse parsed run JSON and log tails across collector ticks.

    JSON entries are reused only when ``(exists, mtime_ns, size)`` is
    unchanged. Log tails are reused only when size is unchanged. Stat
    failures fail open and bypass the cache.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._json: OrderedDict[str, tuple[_FileIdentity, object]] = OrderedDict()
        self._tails: OrderedDict[str, tuple[int, str]] = OrderedDict()
        self.stats = AxeCollectorStats()

    def begin_tick(self) -> None:
        """Reset per-tick counters. Persistent entries are kept."""
        with self._lock:
            self.stats = AxeCollectorStats()

    def snapshot_stats(self) -> AxeCollectorStats:
        """Return a copy of this tick's counters."""
        with self._lock:
            return dataclasses.replace(self.stats)

    def get_or_load_json(
        self,
        path: Path,
        loader: Callable[[], T],
        *,
        kind: JsonKind,
    ) -> T:
        """Return *loader()* unless *path* is cached at the same identity."""
        key = str(path)
        identity = _stat_identity(path)
        if identity is not None:
            with self._lock:
                cached = self._json.get(key)
                if cached is not None and cached[0] == identity:
                    self._json.move_to_end(key)
                    if kind == "run":
                        self.stats.run_json_cache_hits += 1
                    else:
                        self.stats.run_index_cache_hits += 1
                    return cached[1]  # type: ignore[return-value]
        value = loader()
        with self._lock:
            if kind == "run":
                self.stats.run_json_parses += 1
            else:
                self.stats.run_index_reads += 1
            if identity is None or identity.exists:
                self.stats.file_opens += 1
            if identity is not None:
                self._json[key] = (identity, value)
                self._json.move_to_end(key)
                while len(self._json) > _MAX_JSON_ENTRIES:
                    self._json.popitem(last=False)
        return value

    def get_or_load_tail(
        self,
        path: Path,
        loader: Callable[[], str],
        *,
        want: bool,
    ) -> str:
        """Return a log tail, reading only when *want* is set and size grew.

        When *want* is false, a previously cached tail is returned without
        a disk read; otherwise the empty string.
        """
        key = str(path)
        if not want:
            with self._lock:
                cached = self._tails.get(key)
                if cached is not None:
                    self.stats.log_tail_cache_hits += 1
                    self._tails.move_to_end(key)
                    return cached[1]
            return ""
        identity = _stat_identity(path)
        if identity is not None:
            size_key = identity.size if identity.exists else 0
            with self._lock:
                cached = self._tails.get(key)
                if cached is not None and cached[0] == size_key:
                    self.stats.log_tail_cache_hits += 1
                    self._tails.move_to_end(key)
                    return cached[1]
        else:
            size_key = None
        value = loader()
        with self._lock:
            self.stats.log_tail_reads += 1
            if identity is None or identity.exists:
                self.stats.file_opens += 1
            if size_key is not None:
                self._tails[key] = (size_key, value)
                self._tails.move_to_end(key)
                while len(self._tails) > _MAX_TAIL_ENTRIES:
                    self._tails.popitem(last=False)
        return value


__all__ = ["AxeCollectorStats", "AxeStatusReadCache"]

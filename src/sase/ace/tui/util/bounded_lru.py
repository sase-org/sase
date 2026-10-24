"""Small thread-safe LRU cache for bounded TUI presentation state."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import TypeVar, overload

_T = TypeVar("_T")


class BoundedLRUCache[K, V](OrderedDict[K, V]):
    """An ``OrderedDict`` that bounds ownership and serializes mutations.

    ``peek`` supports cache entries whose validity is checked after lookup:
    callers touch recency only after confirming a hit. Ordinary ``get`` and
    item access are LRU hits and refresh recency immediately.
    """

    def __init__(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        super().__init__()
        self.max_entries = max_entries
        self._lock = RLock()

    def __getitem__(self, key: K) -> V:
        with self._lock:
            value = super().__getitem__(key)
            super().move_to_end(key)
            return value

    @overload
    def get(self, key: K, default: None = None, /) -> V | None: ...

    @overload
    def get(self, key: K, default: V, /) -> V: ...

    @overload
    def get(self, key: K, default: _T, /) -> V | _T: ...

    def get(self, key: K, default: object = None, /) -> object:
        with self._lock:
            try:
                value = super().__getitem__(key)
            except KeyError:
                return default
            super().move_to_end(key)
            return value

    def peek(self, key: K, default: V | None = None) -> V | None:
        """Read an entry without changing its eviction priority."""
        with self._lock:
            try:
                return super().__getitem__(key)
            except KeyError:
                return default

    def touch(self, key: K) -> bool:
        """Refresh recency if *key* is still present."""
        with self._lock:
            if key not in self:
                return False
            super().move_to_end(key)
            return True

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            super().__setitem__(key, value)
            super().move_to_end(key)
            while len(self) > self.max_entries:
                super().popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            super().clear()

    def __len__(self) -> int:
        with self._lock:
            return super().__len__()

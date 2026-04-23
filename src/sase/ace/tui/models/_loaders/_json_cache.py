"""Mtime-keyed JSON parse cache for artifact loaders.

The ace TUI re-reads the same JSON artifact files on every refresh. Most of
those files are immutable once written (done.json, completed
workflow_state.json, prompt_step_*.json, dismissed bundles), so parsing them
repeatedly is pure waste. This module provides a small LRU cache keyed on
``(path, st_mtime_ns, st_size)`` — any write to the file bumps mtime and
invalidates the entry automatically.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any

_CACHE_CAP = 4096


class _MTimeJsonCache:
    """Thread-safe LRU cache of parsed JSON keyed on (path, mtime_ns, size)."""

    def __init__(self, cap: int = _CACHE_CAP) -> None:
        self._cap = cap
        self._data: OrderedDict[str, tuple[int, int, Any]] = OrderedDict()
        self._lock = Lock()

    def get(self, path: str | Path) -> Any:
        """Return parsed JSON for *path*, using the cache when fresh.

        Raises the same exceptions as ``open``/``json.load`` for callers that
        want to handle missing/malformed files themselves.
        """
        p = os.fspath(path)
        try:
            st = os.stat(p)
        except OSError:
            with self._lock:
                self._data.pop(p, None)
            raise
        mtime_ns = st.st_mtime_ns
        size = st.st_size
        with self._lock:
            cached = self._data.get(p)
            if cached is not None and cached[0] == mtime_ns and cached[1] == size:
                self._data.move_to_end(p)
                return cached[2]

        with open(p, encoding="utf-8") as f:
            value = json.load(f)

        with self._lock:
            self._data[p] = (mtime_ns, size, value)
            self._data.move_to_end(p)
            while len(self._data) > self._cap:
                self._data.popitem(last=False)
        return value


_JSON_CACHE = _MTimeJsonCache()


def load_json_cached(path: str | Path) -> Any:
    """Load and parse JSON at *path*, memoized by file mtime + size."""
    return _JSON_CACHE.get(path)


def _default_worker_count() -> int:
    return min(8, (os.cpu_count() or 4))


_LOADER_EXECUTOR: Any = None
_EXECUTOR_LOCK = Lock()


def get_loader_executor() -> Any:
    """Return a process-wide ThreadPoolExecutor for parallel JSON reads.

    The pool is created lazily; callers should use ``executor.map()`` or
    ``executor.submit()`` and never shut it down — it lives for the life of
    the process and is shared across refreshes.
    """
    global _LOADER_EXECUTOR
    if _LOADER_EXECUTOR is None:
        with _EXECUTOR_LOCK:
            if _LOADER_EXECUTOR is None:
                from concurrent.futures import ThreadPoolExecutor

                _LOADER_EXECUTOR = ThreadPoolExecutor(
                    max_workers=_default_worker_count(),
                    thread_name_prefix="sase-loader",
                )
    return _LOADER_EXECUTOR

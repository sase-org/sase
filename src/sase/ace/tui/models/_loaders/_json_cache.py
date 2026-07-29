"""Mtime-keyed JSON parse cache for artifact loaders.

The ace TUI re-reads the same JSON artifact files on every refresh. Most of
those files are immutable once written (done.json, completed
workflow_state.json, prompt_step_*.json, dismissed bundles), so parsing them
repeatedly is pure waste. This module provides a small LRU cache keyed on
``(path, st_mtime_ns, st_size)``. Very recent files bypass cached hits because
some filesystems can report the same stat signature for rapid rewrites.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from time import time_ns
from typing import Any

_CACHE_CAP = 4096
_HOT_FILE_CACHE_BYPASS_NS = 1_000_000_000


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
        stable_for_cache = time_ns() - mtime_ns >= _HOT_FILE_CACHE_BYPASS_NS
        with self._lock:
            cached = self._data.get(p)
            if (
                cached is not None
                and stable_for_cache
                and cached[0] == mtime_ns
                and cached[1] == size
            ):
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
    ``executor.submit()``. It is shared across refreshes and should only be
    torn down by ``shutdown_loader_executor()`` during TUI/process teardown.
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


def shutdown_loader_executor() -> None:
    """Cancel queued loader work and detach the shared executor.

    ``ThreadPoolExecutor`` workers are non-daemon threads. If queued loader
    work is left behind during interpreter shutdown, Python drains the whole
    queue before process exit. Cancelling pending futures here leaves only the
    already-running reads to finish.
    """
    global _LOADER_EXECUTOR
    with _EXECUTOR_LOCK:
        executor = _LOADER_EXECUTOR
        _LOADER_EXECUTOR = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def is_loader_executor_shutdown_error(exc: RuntimeError) -> bool:
    """Return True for executor errors caused by shutdown/interpreter teardown."""
    return "cannot schedule new futures after" in str(exc)

"""Process-local serialization for dismissed-index SQLite operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from threading import RLock

_DISMISSED_INDEX_OPERATION_LOCK = RLock()


@contextmanager
def dismissed_index_operation_lock() -> Iterator[None]:
    """Serialize Python and Rust operations on the dismissed index."""
    with _DISMISSED_INDEX_OPERATION_LOCK:
        yield


@contextmanager
def _try_dismissed_index_operation_lock(
    timeout_seconds: float = 2.0,
) -> Iterator[bool]:
    """Try to enter the dismissed-index lock within a bounded window."""
    acquired = _DISMISSED_INDEX_OPERATION_LOCK.acquire(
        timeout=max(0.0, timeout_seconds)
    )
    try:
        yield acquired
    finally:
        if acquired:
            _DISMISSED_INDEX_OPERATION_LOCK.release()


@contextmanager
def bounded_dismissed_index_operation_lock(
    timeout_seconds: float = 2.0,
) -> Iterator[None]:
    """Acquire the lock for a bounded API call or raise SQLite's busy error."""
    with _try_dismissed_index_operation_lock(timeout_seconds) as acquired:
        if not acquired:
            raise sqlite3.OperationalError("dismissed bundle index is busy")
        yield


__all__ = [
    "bounded_dismissed_index_operation_lock",
    "dismissed_index_operation_lock",
]

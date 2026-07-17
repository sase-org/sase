"""Process-local serialization for artifact-index SQLite operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

_ARTIFACT_INDEX_OPERATION_LOCK = RLock()


@contextmanager
def agent_artifact_index_operation_lock() -> Iterator[None]:
    """Serialize artifact-index readers, writers, and repair work in-process."""
    with _ARTIFACT_INDEX_OPERATION_LOCK:
        yield


@contextmanager
def try_agent_artifact_index_operation_lock(
    timeout_seconds: float,
) -> Iterator[bool]:
    """Try to enter the process-local index lock within a bounded window."""
    acquired = _ARTIFACT_INDEX_OPERATION_LOCK.acquire(timeout=max(0.0, timeout_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            _ARTIFACT_INDEX_OPERATION_LOCK.release()


__all__ = [
    "agent_artifact_index_operation_lock",
    "try_agent_artifact_index_operation_lock",
]

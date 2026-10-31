"""Process-local serialization for artifact-index SQLite operations.

The lock serializes in-process index readers, writers, and repair work. It
is process-local: SQLite WAL already allows concurrent readers across
processes. Bounded readers must degrade to cached data, never to a source
scan.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

_ARTIFACT_INDEX_OPERATION_LOCK = RLock()

# Keep this beside the bounded lock operation so facade imports do not need
# to load the heavier agent-scan implementation modules just for a default.
DEFAULT_READ_LOCK_TIMEOUT_SECONDS = 0.05


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
    "DEFAULT_READ_LOCK_TIMEOUT_SECONDS",
    "agent_artifact_index_operation_lock",
    "try_agent_artifact_index_operation_lock",
]

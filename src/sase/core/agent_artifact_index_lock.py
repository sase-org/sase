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


__all__ = ["agent_artifact_index_operation_lock"]

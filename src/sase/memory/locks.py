"""Shared lock helpers for memory state files."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def locked_file(lock_path: Path, flags: int) -> Iterator[None]:
    """Hold a flock on ``lock_path`` for the duration of the context."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), flags)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

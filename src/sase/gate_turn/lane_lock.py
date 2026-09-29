"""Per-lane gate-turn creation lock shared by creation, reclaim, and cancel."""

from __future__ import annotations

import errno
import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.logs._bounded import log_file_lock


@contextmanager
def gate_lane_lock(project_name: str, lane: str) -> Iterator[None]:
    """Hold one lane's gate-turn creation lock, blocking until it is free."""
    with log_file_lock(_lane_lock_base(project_name, lane)):
        yield


@contextmanager
def try_gate_lane_lock(project_name: str, lane: str) -> Iterator[bool]:
    """Yield whether one lane's gate-turn creation lock could be acquired.

    Reclaim and cancel only ever *try* the lock so they never block on a
    slow creator: ``True`` means no creation transaction is running on this
    lane, ``False`` means one is (or a replay is) and the caller must defer.
    """
    base = _lane_lock_base(project_name, lane)
    base.parent.mkdir(parents=True, exist_ok=True)
    lock_path = base.with_name(f".{base.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if not _is_lock_unavailable(exc):
                raise
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _lane_lock_base(project_name: str, lane: str) -> Path:
    """Return the base path whose sibling lock file coordinates one lane."""
    key = sha256(f"{project_name}\0{lane}".encode()).hexdigest()[:32]
    return (
        sase_projects_dir()
        / project_name
        / "artifacts"
        / "ace-run"
        / f".gate-turn-{key}"
    )


def _is_lock_unavailable(exc: OSError) -> bool:
    """Return whether *exc* means the non-blocking flock lost a race."""
    return isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
    }


__all__ = [
    "gate_lane_lock",
    "try_gate_lane_lock",
]

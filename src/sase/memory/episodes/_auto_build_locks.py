"""Lock helpers for the automatic episode builder."""

from __future__ import annotations

import errno
import fcntl
from pathlib import Path
import time

from sase.memory.episodes._auto_build_types import HeldLock


def try_acquire_episode_lock(lock_path: Path, flags: int) -> HeldLock | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    handle = lock_path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), flags | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return None
        raise
    return HeldLock(handle=handle, wait_seconds=time.perf_counter() - started)


def release_episode_lock(lock: HeldLock) -> None:
    try:
        fcntl.flock(lock.handle.fileno(), fcntl.LOCK_UN)
    finally:
        lock.handle.close()


def lock_available(lock_path: Path) -> bool:
    held = try_acquire_episode_lock(lock_path, fcntl.LOCK_EX)
    if held is None:
        return False
    release_episode_lock(held)
    return True

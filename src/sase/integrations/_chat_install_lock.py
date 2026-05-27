"""Lock management for detached chat install/update jobs."""

from __future__ import annotations

import fcntl
import os

from ._chat_install_paths import _LOCK_FD_ENV, lock_path, state_dir


def acquire_lock() -> int | None:
    current_lock_path = lock_path()
    state_dir().mkdir(parents=True, exist_ok=True)
    fd = os.open(current_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def adopt_lock_fd() -> int | None:
    raw = os.environ.pop(_LOCK_FD_ENV, None)
    if raw is None:
        return None
    try:
        fd = int(raw)
        fd_stat = os.fstat(fd)
        lock_stat = lock_path().stat()
    except (OSError, ValueError):
        return None
    if (fd_stat.st_dev, fd_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        return None
    return fd


def lock_is_held() -> bool:
    current_lock_path = lock_path()
    state_dir().mkdir(parents=True, exist_ok=True)
    fd = os.open(current_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)

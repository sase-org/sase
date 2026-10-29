"""Small helpers for checking persisted gate follow-up attempt liveness."""

from __future__ import annotations

import errno
import fcntl
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ATTEMPT_LIVE_FIELD = "gate_followup_attempt_live"
ATTEMPT_OWNER_PID_FIELD = "gate_followup_attempt_owner_pid"
FOLLOWUP_LOCK_NAME = ".gate_followup.lock"


def gate_followup_attempt_is_live(
    meta: Mapping[str, Any], *, artifacts_dir: str | None = None
) -> bool:
    """Return whether the recorded follow-up attempt still owns its lock.

    Callers holding the follow-up lock must not call this probe: an exclusive
    lock holder would observe its own lock and report the attempt as live.
    """
    if not bool(meta.get(ATTEMPT_LIVE_FIELD)):
        return False
    known_artifacts_dir = artifacts_dir or meta.get("artifacts_dir")
    if isinstance(known_artifacts_dir, str) and known_artifacts_dir:
        lock_state = _followup_lock_is_held(known_artifacts_dir)
        if lock_state is not None:
            return lock_state

    owner_pid = _optional_int(meta.get(ATTEMPT_OWNER_PID_FIELD))
    if owner_pid is None:
        return True

    from sase.ace.hooks.processes import is_process_running

    return is_process_running(owner_pid)


def _followup_lock_is_held(artifacts_dir: str) -> bool | None:
    """Probe an existing follow-up lock without creating its lock file."""
    lock_path = Path(artifacts_dir) / FOLLOWUP_LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if isinstance(exc, BlockingIOError) or exc.errno in {
                errno.EACCES,
                errno.EAGAIN,
            }:
                return True
            return None
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
    finally:
        os.close(fd)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ATTEMPT_LIVE_FIELD",
    "ATTEMPT_OWNER_PID_FIELD",
    "FOLLOWUP_LOCK_NAME",
    "gate_followup_attempt_is_live",
]

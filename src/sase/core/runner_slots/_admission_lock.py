"""Host-wide runner-slot admission lock.

Hold publication and the final pre-run admission transition share this lock
so an arm cannot complete unnoticed between a hold snapshot and claim or
proc dispatch commit. Whichever side acquires it first wins: a completed
arm is visible to the next admission check, and a committed claim or proc
dispatch is immune to a later arm.

Lock order, outermost first:

1. Bundle admission lock (per-request ``launch_admission`` lock)
2. ``runner_slots.lock`` (this module)
3. Hold store lock (``agent_holds.lock``, acquired in Rust)

Do not invert this order. Pending capture, liveness index walks,
notifications, and process spawn stay outside (2) and (3). This lock is
not reentrant across distinct file descriptors: a same-thread nested
acquire deadlocks, which is a caller bug (do not arm while holding it).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path

from sase.core.paths import sase_home

_LOCK_FILENAME = "runner_slots.lock"


def runner_slot_lock_path() -> Path:
    """Return the host-wide runner-slot admission lock path."""
    return sase_home() / _LOCK_FILENAME


@contextmanager
def runner_slot_admission_lock() -> Iterator[None]:
    """Hold ``runner_slots.lock`` for one publication or admission transition."""
    lock_path = runner_slot_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

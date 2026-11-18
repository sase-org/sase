"""Routine-local cooperative stop signal for chop launch recovery.

Signal handlers set state only; workers observe the flag at safe
boundaries (between members, before new worker dispatch) and perform
journaling/notification work there. One instance is owned per routine
tick/run so a SIGTERM pause finishes the current launch and starts no
further member, preserving the existing service stop deadline.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class ChopStopSignal:
    """Thread-safe stop flag shared across launch workers."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request_stop(self) -> None:
        """Record a shutdown request; safe to call from a signal handler."""
        self._event.set()

    def stop_requested(self) -> bool:
        """Return whether shutdown has been requested."""
        return self._event.is_set()

    def __call__(self) -> bool:
        """Allow direct use as a ``pause_requested_fn``."""
        return self._event.is_set()

    def as_pause_fn(self) -> Callable[[], bool]:
        """Return a ``pause_requested_fn`` bound to this signal."""
        return self.stop_requested


__all__ = ["ChopStopSignal"]

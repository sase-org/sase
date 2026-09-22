"""Child process-group signal forwarding for the ToolRun executor.

The wrapper installs SIGINT/SIGTERM handlers on its main thread and forwards
the first of each to the child's process group once the group exists.
"""

from __future__ import annotations

import os
import signal
import threading


class SignalState:
    def __init__(self) -> None:
        self.sigint = False
        self.sigterm = False
        self.pgid: int | None = None
        self._forwarded: set[int] = set()
        self._lock = threading.Lock()

    def handler(self, signum: int, _frame: object) -> None:
        with self._lock:
            if signum == signal.SIGINT:
                self.sigint = True
            elif signum == signal.SIGTERM:
                self.sigterm = True
            self._forward_locked(signum)

    def bind_pgid(self, pgid: int) -> None:
        with self._lock:
            self.pgid = pgid
            if self.sigint:
                self._forward_locked(signal.SIGINT)
            if self.sigterm:
                self._forward_locked(signal.SIGTERM)

    def _forward_locked(self, signum: int) -> None:
        if self.pgid is None or signum in self._forwarded:
            return
        self._forwarded.add(signum)
        try:
            os.killpg(self.pgid, signum)
        except (ProcessLookupError, PermissionError, OSError):
            pass


__all__ = ["SignalState"]

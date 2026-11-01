"""Signal-safe guard for agent-side gate entry.

Converts SIGTERM/SIGHUP/SIGINT into a dedicated BaseException so the
existing compensation (failed settlement, claim restore, published-gate
compensation, reservation release, intent clear) runs instead of the
process dying mid-write.
"""

from __future__ import annotations

import signal
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class GateEntrySignal(BaseException):
    """Termination signal received during gate entry."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"gate entry interrupted by signal {signum}")


@contextmanager
def gate_entry_signal_guard() -> Iterator[None]:
    """Convert termination signals into GateEntrySignal for one gate entry.

    Restores previous handlers on exit so the handoff kill that follows a
    published gate uses the process default disposition. Signals arriving
    while compensation for a first signal is running are deferred until
    the compensation finishes.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    state: dict[str, object] = {"interrupted": False, "deferred": None}

    def _handler(signum: int, _frame: object | None) -> None:
        if bool(state["interrupted"]):
            state["deferred"] = signum
            return
        state["interrupted"] = True
        raise GateEntrySignal(signum)

    previous: dict[Any, Any] = {}
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        try:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, _handler)
        except (OSError, ValueError, RuntimeError):
            continue
    try:
        yield
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError, RuntimeError):
                pass
        deferred = state["deferred"]
        if isinstance(deferred, int) and sys.exception() is None:
            raise GateEntrySignal(deferred)


__all__ = ["GateEntrySignal", "gate_entry_signal_guard"]

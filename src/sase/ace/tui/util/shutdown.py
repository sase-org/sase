"""Process-wide cooperative shutdown signal for ACE worker sweeps."""

from __future__ import annotations

import threading


class _ShutdownSignal:
    def __init__(self) -> None:
        self._requested = threading.Event()

    def request(self) -> None:
        self._requested.set()

    def is_requested(self) -> bool:
        return self._requested.is_set()

    def reset_for_tests(self) -> None:
        self._requested.clear()


_shutdown_signal = _ShutdownSignal()


def request_shutdown() -> None:
    """Tell cooperative ACE workers to stop before their next blocking call."""
    _shutdown_signal.request()

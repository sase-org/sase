"""Shared fakes and readers for stall-watchdog TUI tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "FakeClock",
    "FakePumpApp",
    "read_records",
]


class _FakePumpApp:
    """Queue pump callbacks until the test explicitly delivers them."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def call_later(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def deliver(self) -> None:
        callback = self.callbacks.pop(0)
        callback()


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _read_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


FakePumpApp = _FakePumpApp

FakeClock = _FakeClock

read_records = _read_records

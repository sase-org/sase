"""Tests for ``sase.ace.tui.util.io_async.schedule_persist``."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sase.ace.tui.util.io_async import schedule_persist


class FakeApp:
    """Minimal AppLike fake for unit tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.scheduled: list[Any] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.scheduled.append((callback, args, kwargs))


def test_schedule_persist_runs_persist_fn_and_calls_on_success() -> None:
    app = FakeApp()
    calls: list[tuple[int, str]] = []
    successes: list[int] = []

    def persist(a: int, b: str) -> int:
        calls.append((a, b))
        return 42

    schedule_persist(
        app,
        persist,
        7,
        "x",
        error_label="test",
        on_success=successes.append,
    )

    assert len(app.scheduled) == 1
    callback = app.scheduled[0][0]
    asyncio.run(callback())

    assert calls == [(7, "x")]
    assert successes == [42]
    assert app.notifications == []


def test_schedule_persist_failure_notifies_and_calls_on_error() -> None:
    app = FakeApp()
    seen: list[BaseException] = []

    def persist() -> None:
        raise RuntimeError("boom")

    schedule_persist(
        app,
        persist,
        error_label="Approve persist",
        on_error=seen.append,
    )

    callback = app.scheduled[0][0]
    asyncio.run(callback())

    assert app.notifications == [("Approve persist failed: boom", "error")]
    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)


def test_schedule_persist_failure_without_on_error_still_notifies() -> None:
    app = FakeApp()

    def persist() -> None:
        raise OSError("disk full")

    schedule_persist(app, persist, error_label="Persist")

    callback = app.scheduled[0][0]
    asyncio.run(callback())

    assert app.notifications == [("Persist failed: disk full", "error")]


def test_schedule_persist_callbacks_isolate_failures() -> None:
    """A throwing on_success callback must not propagate."""
    app = FakeApp()

    def persist() -> int:
        return 1

    def on_success(value: int) -> None:
        del value
        raise ValueError("callback bug")

    schedule_persist(
        app,
        persist,
        error_label="Persist",
        on_success=on_success,
    )

    callback = app.scheduled[0][0]
    # Must not raise — failures in on_success should be logged, not bubble up.
    asyncio.run(callback())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

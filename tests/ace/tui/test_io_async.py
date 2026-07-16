"""Tests for ``sase.ace.tui.util.io_async._schedule_persist``."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sase.ace.tui.util.io_async import _schedule_persist


class FakeApp:
    """Minimal AppLike fake for unit tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


async def _drain_pump_free_tasks(app: FakeApp) -> None:
    await asyncio.gather(*list(app._pump_free_async_tasks))


@pytest.mark.asyncio
async def test__schedule_persist_runs_persist_fn_and_calls_on_success() -> None:
    app = FakeApp()
    calls: list[tuple[int, str]] = []
    successes: list[int] = []

    def persist(a: int, b: str) -> int:
        calls.append((a, b))
        return 42

    _schedule_persist(
        app,
        persist,
        7,
        "x",
        error_label="test",
        on_success=successes.append,
    )

    await _drain_pump_free_tasks(app)

    assert calls == [(7, "x")]
    assert successes == [42]
    assert app.notifications == []


@pytest.mark.asyncio
async def test__schedule_persist_failure_notifies_and_calls_on_error() -> None:
    app = FakeApp()
    seen: list[BaseException] = []

    def persist() -> None:
        raise RuntimeError("boom")

    _schedule_persist(
        app,
        persist,
        error_label="Approve persist",
        on_error=seen.append,
    )

    await _drain_pump_free_tasks(app)

    assert app.notifications == [("Approve persist failed: boom", "error")]
    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)


@pytest.mark.asyncio
async def test__schedule_persist_failure_without_on_error_still_notifies() -> None:
    app = FakeApp()

    def persist() -> None:
        raise OSError("disk full")

    _schedule_persist(app, persist, error_label="Persist")

    await _drain_pump_free_tasks(app)

    assert app.notifications == [("Persist failed: disk full", "error")]


@pytest.mark.asyncio
async def test__schedule_persist_callbacks_isolate_failures() -> None:
    """A throwing on_success callback must not propagate."""
    app = FakeApp()

    def persist() -> int:
        return 1

    def on_success(value: int) -> None:
        del value
        raise ValueError("callback bug")

    _schedule_persist(
        app,
        persist,
        error_label="Persist",
        on_success=on_success,
    )

    # Must not raise — failures in on_success should be logged, not bubble up.
    await _drain_pump_free_tasks(app)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

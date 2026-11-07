"""Regression coverage for sase's TUI raw pilot pause settling."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widget import Widget


_ORIGINAL_PILOT_PAUSE = Pilot.pause
_LEAK_SENTINEL: Any = None


class _PauseWidget(Widget):
    pass


class _PauseApp(App[None]):
    CSS = "#pause-widget { width: 1; height: 1; }"

    def compose(self) -> ComposeResult:
        yield _PauseWidget(id="pause-widget")


async def test_bare_pilot_pause_uses_event_driven_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_wait_for_idle(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("bare pilot.pause() should not use CPU-idle")

    monkeypatch.setattr("textual.pilot.wait_for_idle", fail_wait_for_idle)

    app = _PauseApp()
    async with app.run_test() as pilot:
        await pilot.pause()


async def test_numeric_pilot_pause_remains_requested_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []

    async def record_sleep(delay: float) -> None:
        calls.append(delay)

    monkeypatch.setattr("textual.pilot.asyncio.sleep", record_sleep)

    app = _PauseApp()
    async with app.run_test() as pilot:
        calls.clear()
        await pilot.pause(0.025)
        assert calls == [0.025]


def test_fixture_patch_can_be_overridden_per_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global _LEAK_SENTINEL

    async def sentinel(self: Pilot, delay: float | None = None) -> None:
        del self, delay

    assert Pilot.pause is not _ORIGINAL_PILOT_PAUSE
    _LEAK_SENTINEL = sentinel
    monkeypatch.setattr(Pilot, "pause", sentinel)
    assert Pilot.pause is sentinel


def test_fixture_patch_does_not_leak_from_previous_test() -> None:
    """No earlier test's ``Pilot.pause`` override survives into this one.

    This must hold in any order: ``tools/run_pytest`` distributes with
    ``--dist worksteal``, so the override test above can run later or on
    another worker. The fixture wraps whatever ``Pilot.pause`` is when it
    runs, so a leaked override from any earlier test on this worker would
    sit under the wrapper instead of the real pause.
    """
    assert Pilot.pause is not _ORIGINAL_PILOT_PAUSE
    assert getattr(Pilot.pause, "__wrapped__", None) is _ORIGINAL_PILOT_PAUSE
    if _LEAK_SENTINEL is not None:  # the override test already ran here
        assert Pilot.pause is not _LEAK_SENTINEL

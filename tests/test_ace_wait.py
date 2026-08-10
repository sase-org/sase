"""Tests for ACE event-driven test settling and bounded wait polling."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widget import Widget

from sase.ace.testing.settle import pause_until_cpu_idle, settle_pilot
from sase.ace.testing.wait import _poll_until


class _SettleWidget(Widget):
    def __init__(self) -> None:
        super().__init__(id="settle")
        self.work_done = False


class _SettleApp(App[None]):
    CSS = "#settle { width: 1; height: 1; }"

    def compose(self) -> ComposeResult:
        yield _SettleWidget()


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


async def _noop_settle() -> None:
    return None


async def test_settle_pilot_drains_widget_work_and_refresh_without_cpu_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_wait_for_idle(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("CPU-idle heuristic should not run")

    monkeypatch.setattr("textual._wait.wait_for_idle", fail_wait_for_idle)
    monkeypatch.setattr("textual.pilot.wait_for_idle", fail_wait_for_idle)

    app = _SettleApp()
    async with app.run_test() as pilot:
        widget = app.query_one("#settle", _SettleWidget)
        refreshed = asyncio.Event()
        widget.call_later(setattr, widget, "work_done", True)
        widget.refresh()
        app.call_after_refresh(refreshed.set)

        await settle_pilot(pilot)

        assert widget.work_done is True
        assert refreshed.is_set()


class _WedgedApp:
    """An app whose frame barrier never resolves, as a closed pump's would not."""

    def __init__(self, *, is_running: bool) -> None:
        self.is_running = is_running
        self.wait_calls = 0

    async def wait_for_refresh(self) -> bool:
        self.wait_calls += 1
        await asyncio.Event().wait()
        return True


class _WedgedPilot:
    def __init__(self, app: _WedgedApp) -> None:
        self.app = app


async def _skip_pause(_pilot: object, _delay: float | None) -> None:
    return None


async def test_settle_pilot_skips_frame_barrier_for_a_stopped_app() -> None:
    app = _WedgedApp(is_running=False)

    await asyncio.wait_for(
        settle_pilot(_WedgedPilot(app), _pilot_pause=_skip_pause), timeout=5
    )

    assert app.wait_calls == 0


async def test_settle_pilot_bounds_a_frame_barrier_that_never_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.testing.settle._REFRESH_TIMEOUT_SECONDS", 0.01, raising=True
    )
    app = _WedgedApp(is_running=True)

    await asyncio.wait_for(
        settle_pilot(_WedgedPilot(app), _pilot_pause=_skip_pause), timeout=5
    )

    assert app.wait_calls == 1


async def test_pause_until_cpu_idle_uses_textual_cpu_idle_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []

    async def record_wait_for_idle(min_sleep: float = 0, max_sleep: float = 1) -> None:
        del max_sleep
        calls.append(min_sleep)

    monkeypatch.setattr("textual.pilot.wait_for_idle", record_wait_for_idle)

    app = _SettleApp()
    async with app.run_test() as pilot:
        await pause_until_cpu_idle(pilot)

    assert calls == [0]


async def test_poll_until_returns_immediately_without_settling() -> None:
    settles = 0
    clock = _FakeClock()

    async def settle() -> None:
        nonlocal settles
        settles += 1

    result = await _poll_until(
        lambda: "ready",
        is_success=lambda value: value == "ready",
        settle=settle,
        timeout=1.0,
        timeout_message=lambda: "timed out",
        clock=clock,
        sleep=clock.sleep,
    )

    assert result == "ready"
    assert settles == 0
    assert clock.sleeps == []


async def test_poll_until_succeeds_after_queued_settle_work() -> None:
    clock = _FakeClock()
    ready = False
    settles = 0

    async def settle() -> None:
        nonlocal ready, settles
        settles += 1
        ready = True

    await _poll_until(
        lambda: ready,
        is_success=bool,
        settle=settle,
        timeout=1.0,
        timeout_message=lambda: "timed out",
        clock=clock,
        sleep=clock.sleep,
    )

    assert settles == 1
    assert clock.sleeps == []


async def test_poll_until_succeeds_after_backoff_for_off_pump_work() -> None:
    clock = _FakeClock()
    ready = False
    settles = 0

    async def settle() -> None:
        nonlocal settles
        settles += 1

    async def sleep(delay: float) -> None:
        nonlocal ready
        await clock.sleep(delay)
        ready = True

    await _poll_until(
        lambda: ready,
        is_success=bool,
        settle=settle,
        timeout=1.0,
        timeout_message=lambda: "timed out",
        clock=clock,
        sleep=sleep,
        backoff_after_misses=3,
        backoff_seconds=0.01,
    )

    assert settles == 3
    assert clock.sleeps == [0.01]


async def test_poll_until_times_out_with_exact_message() -> None:
    clock = _FakeClock()

    with pytest.raises(AssertionError) as excinfo:
        await _poll_until(
            lambda: False,
            is_success=bool,
            settle=_noop_settle,
            timeout=0.0,
            timeout_message=lambda: "exact timeout text",
            clock=clock,
            sleep=clock.sleep,
        )

    assert str(excinfo.value) == "exact timeout text"


async def test_poll_until_backs_off_instead_of_spinning() -> None:
    clock = _FakeClock()
    settles = 0

    async def settle() -> None:
        nonlocal settles
        settles += 1

    with pytest.raises(AssertionError):
        await _poll_until(
            lambda: False,
            is_success=bool,
            settle=settle,
            timeout=0.05,
            timeout_message=lambda: "timed out",
            clock=clock,
            sleep=clock.sleep,
            backoff_after_misses=2,
            backoff_seconds=0.01,
        )

    assert settles == 6
    assert clock.sleeps == [0.01, 0.01, 0.01, 0.01, 0.01]


def test_poll_until_never_sleeps_past_deadline() -> None:
    clock = _FakeClock()

    async def run() -> None:
        with pytest.raises(AssertionError):
            await _poll_until(
                lambda: False,
                is_success=bool,
                settle=_noop_settle,
                timeout=0.015,
                timeout_message=lambda: "timed out",
                clock=clock,
                sleep=clock.sleep,
                backoff_after_misses=1,
                backoff_seconds=0.01,
            )

    asyncio.run(run())

    assert clock.sleeps == pytest.approx([0.01, 0.005])

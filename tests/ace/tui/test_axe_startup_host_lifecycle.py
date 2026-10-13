"""ACE startup drives the service host, never the legacy AXE daemon."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.axe_display._service_restart_transition import (
    SERVICE_RESTART_POST_START_GRACE_SECONDS,
)


class _StartupHarness(AxeMixin):
    def __init__(self, *, running: bool, restart: bool, auto_start: bool) -> None:
        self.axe_running = running
        self._restart_axe = restart
        self._auto_start_axe = auto_start
        self.refreshes = 0
        self._service_status = None
        self._service_restart_transition = None
        self.notifies: list[tuple[str, str]] = []
        self.timers: list[tuple[float, object]] = []

    async def _load_axe_status_async(self, **_kwargs: object) -> None:  # type: ignore[override]
        return

    def _schedule_axe_async_refresh(self) -> None:  # type: ignore[override]
        self.refreshes += 1

    def notify(self, message: str, severity: str = "information") -> None:
        self.notifies.append((message, severity))

    def set_timer(self, delay: float, callback: object) -> object:
        self.timers.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)


def _ok(message: str = "restarted") -> SimpleNamespace:
    return SimpleNamespace(ok=True, changed=True, message=message)


def _not_ok(message: str = "boom") -> SimpleNamespace:
    return SimpleNamespace(ok=False, changed=True, message=message)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("running", "restart", "auto_start", "expected"),
    [
        (False, False, True, ["start"]),
        (True, True, True, ["restart"]),
        (True, False, True, []),
        (False, False, False, []),
        (False, True, True, ["start"]),
    ],
)
async def test_ace_startup_starts_or_restarts_the_service_host(
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
    restart: bool,
    auto_start: bool,
    expected: list[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.service.control.start_service_host",
        lambda: (calls.append("start"), _ok("started"))[1],
    )
    monkeypatch.setattr(
        "sase.service.control.restart_service_host",
        lambda: (calls.append("restart"), _ok())[1],
    )
    app = _StartupHarness(running=running, restart=restart, auto_start=auto_start)

    await app._run_axe_startup_init()

    assert calls == expected
    assert app.refreshes == len(expected)


@pytest.mark.asyncio
async def test_restart_begins_transition_and_schedules_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.service.control.restart_service_host",
        lambda: (calls.append("restart"), _ok())[1],
    )
    app = _StartupHarness(running=True, restart=True, auto_start=True)

    await app._run_axe_startup_init()

    assert calls == ["restart"]
    assert app._service_restart_transition is not None
    assert app.notifies == []
    assert len(app.timers) == 1
    delay, _callback = app.timers[0]
    assert delay == SERVICE_RESTART_POST_START_GRACE_SECONDS


@pytest.mark.asyncio
async def test_restart_not_ok_clears_transition_and_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.service.control.restart_service_host", lambda: _not_ok("timed out")
    )
    app = _StartupHarness(running=True, restart=True, auto_start=True)

    await app._run_axe_startup_init()

    assert app._service_restart_transition is None
    assert len(app.notifies) == 1
    assert "Service host restart failed" in app.notifies[0][0]
    assert "timed out" in app.notifies[0][0]
    assert app.timers == []
    assert app.refreshes == 1


@pytest.mark.asyncio
async def test_restart_exception_clears_transition_and_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> object:
        raise RuntimeError("kaput")

    monkeypatch.setattr("sase.service.control.restart_service_host", _raise)
    app = _StartupHarness(running=True, restart=True, auto_start=True)

    await app._run_axe_startup_init()

    assert app._service_restart_transition is None
    assert len(app.notifies) == 1
    assert "Service host restart failed" in app.notifies[0][0]
    assert app.timers == []
    assert app.refreshes == 1


@pytest.mark.asyncio
async def test_startup_init_after_release_still_auto_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release must not skip auto-start: init still starts the service host."""
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.service.control.start_service_host",
        lambda: (calls.append("start"), _ok("started"))[1],
    )
    app = _StartupHarness(running=False, restart=False, auto_start=True)
    app._startup_deferred_loads_released = True
    app._axe_first_load_done = False

    await app._run_axe_startup_init()

    assert calls == ["start"]
    assert app.refreshes == 1


@pytest.mark.asyncio
async def test_tick_during_startup_init_does_not_start_second_collect() -> None:
    """A status refresh that lands while init owns the running flag coalesces."""
    app = _StartupHarness(running=False, restart=False, auto_start=False)
    collecting = asyncio.Event()
    release = asyncio.Event()
    loads = 0

    async def slow_load(**_kwargs: object) -> None:
        nonlocal loads
        loads += 1
        collecting.set()
        await release.wait()

    app._load_axe_status_async = slow_load  # type: ignore[method-assign]
    app._axe_status_refresh_scheduled = False
    app._axe_status_refresh_running = False
    app._axe_status_refresh_pending = False
    app._axe_status_refresh_want_full = False
    app._axe_status_refresh_want_all_tails = False

    init_task = asyncio.create_task(app._run_axe_startup_init())
    await asyncio.wait_for(collecting.wait(), timeout=1.0)
    refreshed = await app._run_axe_status_refresh()
    assert refreshed is False
    assert loads == 1
    release.set()
    await asyncio.wait_for(init_task, timeout=1.0)
    assert loads == 1

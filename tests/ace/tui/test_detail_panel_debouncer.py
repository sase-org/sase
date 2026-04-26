"""Coalescing semantics of :class:`DetailPanelDebouncer`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.util.debounce import DetailPanelDebouncer


class _StubTimer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _StubApp:
    """Minimal Textual-app surface — captures the most recent timer."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[float, Callable[[], None], _StubTimer]] = []

    def set_timer(self, delay: float, callback: Callable[[], None]) -> Any:
        timer = _StubTimer()
        self.scheduled.append((delay, callback, timer))
        return timer


def test_burst_coalesces_to_single_callback_invocation() -> None:
    """A long press of j fires the callback exactly once on quiesce."""
    app = _StubApp()
    deb = DetailPanelDebouncer(app, delay_s=0.15)  # type: ignore[arg-type]

    fire_count = 0

    def cb() -> None:
        nonlocal fire_count
        fire_count += 1

    for _ in range(20):
        deb.schedule(cb)

    # Every prior timer is stopped; only the most-recent one survives.
    stopped = sum(1 for _, _, t in app.scheduled if t.stopped)
    assert stopped == 19
    assert deb.is_pending

    _, latest_cb, latest_timer = app.scheduled[-1]
    assert not latest_timer.stopped
    latest_cb()

    assert fire_count == 1
    assert not deb.is_pending


def test_cancel_drops_pending_callback_without_firing() -> None:
    app = _StubApp()
    deb = DetailPanelDebouncer(app, delay_s=0.15)  # type: ignore[arg-type]

    fired = False

    def cb() -> None:
        nonlocal fired
        fired = True

    deb.schedule(cb)
    deb.cancel()

    assert not deb.is_pending
    _, _, timer = app.scheduled[-1]
    assert timer.stopped
    assert not fired


def test_most_recent_callback_wins_on_burst() -> None:
    """Intermediate callbacks are discarded; only the final one runs."""
    app = _StubApp()
    deb = DetailPanelDebouncer(app, delay_s=0.15)  # type: ignore[arg-type]

    invoked: list[str] = []

    deb.schedule(lambda: invoked.append("first"))
    deb.schedule(lambda: invoked.append("second"))
    deb.schedule(lambda: invoked.append("third"))

    _, latest_cb, _ = app.scheduled[-1]
    latest_cb()

    assert invoked == ["third"]


def test_reschedule_after_fire_starts_fresh_cycle() -> None:
    app = _StubApp()
    deb = DetailPanelDebouncer(app, delay_s=0.15)  # type: ignore[arg-type]

    deb.schedule(lambda: None)
    _, cb, _ = app.scheduled[-1]
    cb()
    assert not deb.is_pending

    deb.schedule(lambda: None)
    assert deb.is_pending

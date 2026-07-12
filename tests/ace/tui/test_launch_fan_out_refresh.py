"""Launch fan-out refresh coalescing tests."""

from __future__ import annotations

import pytest

from tests.ace.tui._launch_fan_out_helpers import _CoalesceApp


def test_request_agents_refresh_arms_one_timer_for_burst() -> None:
    """A burst of fan-out callbacks collapses into one deferred refresh."""
    app = _CoalesceApp()

    for _ in range(5):
        app.request_agents_refresh("launch")

    assert len(app._timer_calls) == 1
    delay, _ = app._timer_calls[0]
    assert delay == pytest.approx(0.150)
    assert app._agents_refresh_debounce_armed is True


def test_request_agents_refresh_re_arms_after_fire() -> None:
    """Once the debounce fires, the next burst arms a fresh timer."""
    app = _CoalesceApp()

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 1

    # Simulate the timer firing.
    _, fire = app._timer_calls[-1]
    fire()  # type: ignore[misc]
    assert app._agents_refresh_debounce_armed is False
    # The fired timer hands off to _schedule_agents_async_refresh, which
    # spawns _run_agents_async_refresh exactly once.
    scheduled_runs = [
        cb for cb, _ in app._scheduled if cb == app._run_agents_async_refresh
    ]
    assert len(scheduled_runs) == 1

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 2


def test_request_agents_refresh_latest_only_false_resets_window() -> None:
    """``latest_only=False`` schedules a fresh timer for every request."""
    app = _CoalesceApp()

    app.request_agents_refresh("launch", latest_only=False)
    app.request_agents_refresh("launch", latest_only=False)
    app.request_agents_refresh("launch", latest_only=False)

    assert len(app._timer_calls) == 3


@pytest.mark.asyncio
async def test_launch_refresh_respects_navigation_gate() -> None:
    """While j/k is active, the post-burst refresh defers via set_timer."""
    app = _CoalesceApp()
    app._nav_gate.record()

    app.request_agents_refresh("launch")
    assert len(app._timer_calls) == 1

    # Fire the debounce timer manually to simulate the deferred dispatch.
    _, fire = app._timer_calls[0]
    fire()  # type: ignore[misc]

    # _schedule_agents_async_refresh spawns _run_agents_async_refresh. Run it:
    # the gate is hot, so it must defer via set_timer
    # (no actual load yet).
    pending_runs = [
        cb for cb, _ in app._scheduled if cb == app._run_agents_async_refresh
    ]
    assert len(pending_runs) == 1
    app._scheduled.clear()
    await app._run_agents_async_refresh()

    # The gated refresh re-armed itself with a small delay rather than
    # running the apply leg.
    boundary_timers = [
        (d, cb) for d, cb in app._timer_calls if cb == app._spawn_agents_refresh_task
    ]
    assert boundary_timers, (
        "expected a gate-boundary set_timer for _spawn_agents_refresh_task"
    )

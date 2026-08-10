"""Event-driven settling helpers for ACE Textual tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from textual.pilot import Pilot


PilotPause = Callable[[Any, float | None], Awaitable[None]]

_TEXTUAL_PILOT_PAUSE: PilotPause = Pilot.pause

#: Backstop for the frame barrier below. It has to be generous enough that a
#: heavily contended worker never trips it — the bounded waiters in
#: ``wait.py`` already time out at 5s and report a useful message — and it
#: exists only so a wedged app cannot outlive the run itself.
_REFRESH_TIMEOUT_SECONDS = 15.0


async def settle_pilot(
    pilot: Any,
    *,
    _pilot_pause: PilotPause | None = None,
) -> None:
    """Drain Textual work and wait for a rendered frame without CPU-idle polling.

    Textual's zero-delay pause path is still valuable: it queues a ``call_later``
    callback on the app, screen, and widgets, waits for those callbacks, yields
    once, then performs the screen timer update. What ACE tests do not want by
    default is ``Pilot.pause(None)``'s process-wide CPU-idle heuristic, which
    adds a fixed 20 ms sleep and becomes noisy under xdist.

    The extra frame barrier covers callbacks scheduled for after the frame
    Textual just rendered, and the final zero-delay drain lets those callbacks
    run before tests assert on widget state. Keeping these steps here confines
    the private ``Pilot.pause(0)`` compatibility boundary to one module.
    """

    pause = _TEXTUAL_PILOT_PAUSE if _pilot_pause is None else _pilot_pause
    await pause(pilot, 0)
    await _wait_for_frame(pilot.app)
    await pause(pilot, 0)


async def _wait_for_frame(app: Any) -> None:
    """Wait for the next rendered frame without blocking on a dead pump.

    ``MessagePump.wait_for_refresh`` posts a callback that sets an event and
    then awaits that event unconditionally, discarding the ``post_message``
    result that says whether the callback was even accepted. An app whose pump
    has closed — or one that closes before draining the callback — therefore
    leaves the waiter with nothing left to wake it, and since the whole suite
    runs without a per-test timeout, one such settle wedges the run rather than
    failing it. Neither shape can reach this barrier's own caller, so this is
    where both are bounded.
    """

    if not app.is_running:
        return
    try:
        await asyncio.wait_for(app.wait_for_refresh(), _REFRESH_TIMEOUT_SECONDS)
    except TimeoutError:
        return


async def pause_until_cpu_idle(
    pilot: Any,
    *,
    _pilot_pause: PilotPause | None = None,
) -> None:
    """Use Textual's original ``Pilot.pause(None)`` CPU-idle heuristic explicitly."""

    pause = _TEXTUAL_PILOT_PAUSE if _pilot_pause is None else _pilot_pause
    await pause(pilot, None)

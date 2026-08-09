"""Event-driven settling helpers for ACE Textual tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from textual.pilot import Pilot


PilotPause = Callable[[Any, float | None], Awaitable[None]]

_TEXTUAL_PILOT_PAUSE: PilotPause = Pilot.pause


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

    The extra ``wait_for_refresh`` call covers callbacks scheduled for after the
    frame Textual just rendered, and the final zero-delay drain lets those
    callbacks run before tests assert on widget state. Keeping these steps here
    confines the private ``Pilot.pause(0)`` compatibility boundary to one module.
    """

    pause = _TEXTUAL_PILOT_PAUSE if _pilot_pause is None else _pilot_pause
    await pause(pilot, 0)
    await pilot.app.wait_for_refresh()
    await pause(pilot, 0)


async def pause_until_cpu_idle(
    pilot: Any,
    *,
    _pilot_pause: PilotPause | None = None,
) -> None:
    """Use Textual's original ``Pilot.pause(None)`` CPU-idle heuristic explicitly."""

    pause = _TEXTUAL_PILOT_PAUSE if _pilot_pause is None else _pilot_pause
    await pause(pilot, None)

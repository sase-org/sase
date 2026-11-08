"""Bounded-wait polling for tests that drive a raw Textual pilot.

``AcePage.wait_for`` and its ``expect_*`` siblings are the bounded-wait
waiters for ``AcePage`` tests. Tests built directly on ``App.run_test()``
instead of the ``AcePage`` DSL share this helper rather than hand-rolling
their own copy.

A bare ``pilot.pause()`` is sufficient only for work that completes on the
Textual message pump. Anything that crosses a thread, a worker, or a
pump-free task races the pump and must instead be waited on by its
observable end state, with this helper (or an ``AcePage.expect_*`` for
``AcePage`` tests).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from . import settle as settle_helpers


_BACKOFF_AFTER_MISSES = 3
_BACKOFF_SECONDS = 0.001

# Default bound for every condition wait in this package (``wait_for``, the
# ``AcePage`` ``expect_*`` waiters, and ``AcePage`` startup). These bounds are
# hang detectors, not speed assertions: under the default-lane contention soak
# (26 xdist workers pinned to two CPUs) a Textual pump turn or an off-pump
# worker can legitimately take tens of seconds to reach a state that is
# immediate on an idle machine. The value mirrors
# ``tests/_load_tolerant.LOAD_TOLERANT_TIMEOUT``. A caller whose deadline is
# itself the behavior under test passes its own ``timeout``.
DEFAULT_WAIT_TIMEOUT = 60.0


async def _poll_until[T](
    predicate: Callable[[], T | None],
    *,
    is_success: Callable[[T | None], bool],
    settle: Callable[[], Awaitable[None]],
    timeout: float,
    timeout_message: Callable[[], str],
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    backoff_after_misses: int = _BACKOFF_AFTER_MISSES,
    backoff_seconds: float = _BACKOFF_SECONDS,
) -> T | None:
    """Poll a predicate with event-driven settling and a bounded backoff."""

    if clock is None:
        clock = asyncio.get_running_loop().time
    if sleep is None:
        sleep = asyncio.sleep

    deadline = clock() + timeout
    misses = 0
    while True:
        value = predicate()
        if is_success(value):
            return value
        if clock() >= deadline:
            raise AssertionError(timeout_message())

        await settle()
        misses += 1

        if misses < backoff_after_misses:
            continue

        remaining = deadline - clock()
        if remaining <= 0:
            continue
        delay = min(backoff_seconds, remaining)
        if delay > 0:
            await sleep(delay)


async def wait_for(
    pilot: Any,
    predicate: Callable[[], bool],
    *,
    timeout: float = DEFAULT_WAIT_TIMEOUT,
) -> None:
    """Poll *predicate* via event-driven settling until it returns True.

    Raises ``AssertionError`` naming *predicate* and the elapsed timeout if
    it never returns True within *timeout* seconds.
    """

    def timeout_message() -> str:
        name = getattr(predicate, "__qualname__", None) or repr(predicate)
        return (
            f"wait_for({name}) timed out after {timeout}s waiting for it to return True"
        )

    await _poll_until(
        predicate,
        is_success=bool,
        settle=lambda: settle_helpers.settle_pilot(pilot),
        timeout=timeout,
        timeout_message=timeout_message,
    )

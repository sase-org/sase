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
from collections.abc import Callable
from typing import Any


async def wait_for(
    pilot: Any,
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
) -> None:
    """Poll *predicate* via ``pilot.pause()`` until it returns True.

    Raises ``AssertionError`` naming *predicate* and the elapsed timeout if
    it never returns True within *timeout* seconds.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            name = getattr(predicate, "__qualname__", None) or repr(predicate)
            raise AssertionError(
                f"wait_for({name}) timed out after {timeout}s waiting for it"
                " to return True"
            )
        await pilot.pause()

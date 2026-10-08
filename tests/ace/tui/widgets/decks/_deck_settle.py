"""Shared anchor-scroll settle wait for deck pilot tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.testing import wait_for


async def wait_for_anchor_scroll(
    pilot: Any,
    scroll_pos: Callable[[], int],
    live_target: Callable[[], int | None],
    *,
    timeout: float = 5.0,
) -> int:
    """Wait until an anchor scroll settles on its live landing target.

    The landing target depends on layout (published anchors, trailing
    reserve, scrollbar clamping), so it can shift across frames while the
    view settles. Callers must not snapshot it once and wait for equality
    with the stale value: this helper re-reads the target on every poll
    and only succeeds when the scroll position matches the *same* target
    on two consecutive settle iterations, proving the landing converged
    rather than transited through the value.
    """
    last: list[int | None] = [None]

    def settled_on_live_target() -> bool:
        try:
            target = live_target()
        except Exception:
            last[0] = None
            return False
        if target is None:
            last[0] = None
            return False
        try:
            pos = int(scroll_pos())
        except Exception:
            last[0] = None
            return False
        settled = pos == int(target) and last[0] == int(target)
        last[0] = int(target)
        return settled

    await wait_for(pilot, settled_on_live_target, timeout=timeout)
    target = live_target()
    assert target is not None
    return int(target)


__all__ = ["wait_for_anchor_scroll"]

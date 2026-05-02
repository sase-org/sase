"""User-is-navigating gate for deferring background work during j/k bursts.

Phase 5 of sdd/tales/202604/instant_jk_navigation.md (bead sase-u.5). The
:class:`NavigationGate` records the wall-clock of each j/k action; background
reconcilers consult :meth:`is_navigating` to decide whether to fire now or
defer until the user quiesces. The default 250 ms window matches the plan
spec.
"""

from __future__ import annotations

import time

DEFAULT_NAVIGATE_WINDOW_S = 0.25


class NavigationGate:
    """Tracks the timestamp of the most recent j/k action.

    A reconciliation that consults this gate will defer rather than land
    mid-burst — the cursor highlight wins, the background work catches up
    once the user pauses.
    """

    def __init__(self, *, window_s: float = DEFAULT_NAVIGATE_WINDOW_S) -> None:
        if window_s < 0:
            raise ValueError("window_s must be non-negative")
        self._window_s = window_s
        # 0.0 sentinel means "never navigated" — distinguished from
        # ``time.monotonic()`` results which are strictly positive after the
        # process has been alive for any meaningful interval.
        self._last_nav_mono: float = 0.0

    @property
    def window_s(self) -> float:
        return self._window_s

    def record(self, *, now_mono: float | None = None) -> None:
        """Record that the user just pressed j/k."""
        self._last_nav_mono = time.monotonic() if now_mono is None else now_mono

    def is_navigating(self, *, now_mono: float | None = None) -> bool:
        """True when a j/k was recorded within the last ``window_s`` seconds."""
        if self._last_nav_mono == 0.0:
            return False
        cur = time.monotonic() if now_mono is None else now_mono
        return (cur - self._last_nav_mono) < self._window_s

    def time_until_idle(self, *, now_mono: float | None = None) -> float:
        """Seconds remaining until :meth:`is_navigating` returns False.

        ``0.0`` when the user is already idle. Useful for callers that want
        to schedule a deferred retry exactly at the gate boundary.
        """
        if self._last_nav_mono == 0.0:
            return 0.0
        cur = time.monotonic() if now_mono is None else now_mono
        remaining = self._window_s - (cur - self._last_nav_mono)
        return max(0.0, remaining)

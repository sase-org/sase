"""Jittered backoff for parked runner-slot waiters."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

_POLL_JITTER_MIN = 0.85
_POLL_JITTER_MAX = 1.15
_POLL_MAX_MULTIPLIER = 10
_POLL_MAX_SECONDS = 30.0


def _runner_slot_poll_max_interval(base: float) -> float:
    """Return the bounded backoff cap derived from the fast-poll interval."""
    return min(_POLL_MAX_SECONDS, max(base, base * _POLL_MAX_MULTIPLIER))


def _runner_slot_poll_interval(
    attempt: int,
    *,
    base: float,
    max_interval: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Return the next sleep, growing from *base* toward the backoff cap.

    *attempt* is the number of consecutive unchanged polls since the last
    slot-state change or first park. Jitter stays within 15% so a convoy of
    waiters does not share one wake-up instant.
    """
    cap = _runner_slot_poll_max_interval(base) if max_interval is None else max_interval
    exponent = max(0, attempt)
    grown = min(cap, base * (2**exponent))
    picker = rng if rng is not None else random.Random()
    jitter = picker.uniform(_POLL_JITTER_MIN, _POLL_JITTER_MAX)
    return min(cap, max(base * _POLL_JITTER_MIN, grown * jitter))


def _sleep_for_runner_slot_poll(
    timeout: float,
    seen_token: str,
    *,
    probe_interval: float,
    killed: Callable[[], bool],
    token: Callable[[], str],
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Sleep up to *timeout*, returning True if the slot-state token changed.

    The wait is sliced into *probe_interval* chunks so a freed slot wakes
    waiters on the fast-poll cadence instead of waiting out a long backoff.
    """
    if timeout <= 0:
        return token() != seen_token
    deadline = clock() + timeout
    while not killed():
        if token() != seen_token:
            return True
        remaining = deadline - clock()
        if remaining <= 0:
            return token() != seen_token
        sleeper(min(probe_interval, remaining) if probe_interval > 0 else remaining)
    return False


def advance_runner_slot_poll(
    poll_attempt: int,
    seen_token: str,
    *,
    base: float,
    killed: Callable[[], bool],
    token: Callable[[], str],
) -> tuple[int, str]:
    """Sleep one backoff step and return the next attempt and token."""
    current_token = token()
    if current_token != seen_token:
        poll_attempt = 0
        seen_token = current_token
    changed = _sleep_for_runner_slot_poll(
        _runner_slot_poll_interval(
            poll_attempt,
            base=base,
            max_interval=_runner_slot_poll_max_interval(base),
        ),
        seen_token,
        probe_interval=base,
        killed=killed,
        token=token,
    )
    if changed:
        return 0, token()
    return poll_attempt + 1, seen_token


__all__ = [
    "advance_runner_slot_poll",
]

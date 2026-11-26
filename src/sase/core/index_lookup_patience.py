"""Optional bounded patience for transiently busy indexed lookups.

Lookup callers keep their ordinary bounded single attempt unless a process
installs a :class:`LookupPatience` policy. Detached agent runners use the
policy while interactive callers retain their current latency budget.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import math
import threading
import time


@dataclass(frozen=True)
class LookupRetryEvent:
    """One busy retry decision or its final recovery/give-up outcome."""

    lookup: str
    attempt: int
    seconds_waited: float
    next_delay_seconds: float
    last_diagnostic: str | None
    recovered: bool = False
    gave_up: bool = False


@dataclass(frozen=True)
class LookupPatience:
    """Process policy controlling retry of busy-incomplete lookup results."""

    budget_seconds: float
    initial_delay_seconds: float = 0.25
    max_delay_seconds: float = 5.0
    on_retry: Callable[[LookupRetryEvent], object] | None = None

    def __post_init__(self) -> None:
        values = (
            self.budget_seconds,
            self.initial_delay_seconds,
            self.max_delay_seconds,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("lookup patience values must be finite")
        if self.initial_delay_seconds <= 0:
            raise ValueError("initial_delay_seconds must be positive")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds must be at least the initial delay")


_POLICY_LOCK = threading.RLock()
_PROCESS_LOOKUP_PATIENCE: LookupPatience | None = None


def set_process_lookup_patience(patience: LookupPatience | None) -> None:
    """Set the policy visible to every thread in this process."""
    global _PROCESS_LOOKUP_PATIENCE
    with _POLICY_LOCK:
        _PROCESS_LOOKUP_PATIENCE = patience


def _get_process_lookup_patience() -> LookupPatience | None:
    """Return the currently installed process-wide lookup policy."""
    with _POLICY_LOCK:
        return _PROCESS_LOOKUP_PATIENCE


@contextmanager
def process_lookup_patience(patience: LookupPatience | None) -> Iterator[None]:
    """Temporarily install a policy and restore the previous one on exit."""
    previous = _get_process_lookup_patience()
    set_process_lookup_patience(patience)
    try:
        yield
    finally:
        set_process_lookup_patience(previous)


def retry_while_busy[Result](
    attempt: Callable[[], Result],
    *,
    is_busy: Callable[[Result], bool],
    diagnostic: Callable[[Result], str | None],
    lookup: str,
    sleep: Callable[[float], object] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Result:
    """Retry busy results under the process policy and return the last result.

    Exceptions from ``attempt`` retain their existing behavior. This helper
    does not decide what an incomplete result means to its caller; the facade
    raises its usual typed exception after receiving the final result.
    """
    patience = _get_process_lookup_patience()
    if patience is None:
        return attempt()

    started = monotonic()
    deadline = started + max(0.0, patience.budget_seconds)
    delay = max(0.0, patience.initial_delay_seconds)
    result = attempt()
    if not is_busy(result):
        return result

    attempt_number = 1
    while True:
        now = monotonic()
        waited = max(0.0, now - started)
        remaining = deadline - now
        if remaining <= 0:
            _notify(
                patience,
                LookupRetryEvent(
                    lookup=lookup,
                    attempt=attempt_number,
                    seconds_waited=waited,
                    next_delay_seconds=0.0,
                    last_diagnostic=diagnostic(result),
                    gave_up=True,
                ),
            )
            return result

        sleep_for = min(delay, remaining)
        _notify(
            patience,
            LookupRetryEvent(
                lookup=lookup,
                attempt=attempt_number,
                seconds_waited=waited,
                next_delay_seconds=sleep_for,
                last_diagnostic=diagnostic(result),
            ),
        )
        sleep(sleep_for)
        result = attempt()
        attempt_number += 1
        if not is_busy(result):
            _notify(
                patience,
                LookupRetryEvent(
                    lookup=lookup,
                    attempt=attempt_number,
                    seconds_waited=max(0.0, monotonic() - started),
                    next_delay_seconds=0.0,
                    last_diagnostic=diagnostic(result),
                    recovered=True,
                ),
            )
            return result
        delay = min(
            max(delay * 2, patience.initial_delay_seconds), patience.max_delay_seconds
        )


def _notify(patience: LookupPatience, event: LookupRetryEvent) -> None:
    callback = patience.on_retry
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # Logging must never turn a best-effort lookup retry into a failure.
        pass


__all__ = [
    "LookupPatience",
    "LookupRetryEvent",
    "process_lookup_patience",
    "retry_while_busy",
    "set_process_lookup_patience",
]

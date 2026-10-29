"""One consumable wall-clock budget for a rebase-gate attempt."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import time
from typing import Any


class GateBudgetExhausted(TimeoutError):
    """Raised before more gate work starts after its shared budget expires."""


@dataclass
class GateWorkBudget:
    """Track gate-only work while excluding ordinary fetch/rebase/push time.

    Callers wrap each gate operation in :meth:`measure` or :meth:`run`. The
    configured timeout is shared across configuration, Git discovery, hook
    execution, output consumption, and report reads. A small part is reserved
    for bounded process and temporary-file teardown.
    """

    timeout_seconds: float = 10.0
    teardown_reserve_seconds: float = 0.5
    clock: Callable[[], float] = time.monotonic
    spent_seconds: float = 0.0

    def set_timeout(self, timeout_seconds: float) -> None:
        """Apply a Rust-validated project timeout without refunding prior work."""
        self.timeout_seconds = timeout_seconds

    @property
    def _effective_teardown_reserve(self) -> float:
        return min(self.teardown_reserve_seconds, self.timeout_seconds * 0.25)

    @property
    def work_remaining(self) -> float:
        return max(
            0.0,
            self.timeout_seconds
            - self.spent_seconds
            - self._effective_teardown_reserve,
        )

    @property
    def total_remaining(self) -> float:
        return max(0.0, self.timeout_seconds - self.spent_seconds)

    @property
    def teardown_remaining(self) -> float:
        return min(self._effective_teardown_reserve, self.total_remaining)

    def _charge(self, started: float) -> None:
        self.spent_seconds += max(0.0, self.clock() - started)

    def charge_elapsed(self, started: float) -> None:
        """Charge a subprocess section that uses its own internal deadline."""
        self._charge(started)

    @contextmanager
    def measure(self, *, teardown: bool = False) -> Iterator[None]:
        """Measure one bounded gate-only operation against the shared budget."""
        remaining = self.teardown_remaining if teardown else self.work_remaining
        if remaining <= 0:
            raise GateBudgetExhausted("rebase gate work budget exhausted")
        started = self.clock()
        try:
            yield
        finally:
            self._charge(started)

    def run(
        self,
        call: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a command with the remaining budget as its subprocess timeout."""
        remaining = self.work_remaining
        if remaining <= 0:
            raise GateBudgetExhausted("rebase gate work budget exhausted")
        started = self.clock()
        try:
            return call(*args, timeout=remaining, **kwargs)
        finally:
            self._charge(started)

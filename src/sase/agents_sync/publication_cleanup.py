"""Shared one-second bound for best-effort publication cleanup after a drain timeout."""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import subprocess

from sase.agents_sync.git import GitRunner


def default_publication_cleanup_timeout() -> float:
    """Return the required Rust-owned cleanup budget in seconds."""
    from sase.core.agent_publication_recovery import (
        default_publication_cleanup_timeout as core_default,
    )

    return core_default()


class PublicationCleanupTimedOut(TimeoutError):
    """Raised when bounded exception cleanup exhausts its one-second budget."""


class PublicationCleanupBudget:
    """One monotonic deadline shared by both regenerable cleanup families."""

    def __init__(
        self,
        timeout_seconds: float | None = None,
        *,
        deadline: float | None = None,
    ) -> None:
        rust_cap = default_publication_cleanup_timeout()
        if timeout_seconds is None:
            timeout = rust_cap
        else:
            if not (timeout_seconds > 0):
                raise ValueError("publication cleanup timeout must be positive")
            timeout = min(timeout_seconds, rust_cap)
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout if deadline is None else deadline

    def remaining(self) -> float:
        """Return seconds left on the shared cleanup deadline (floor 0)."""
        return max(0.0, self.deadline - time.monotonic())

    def exhausted(self) -> bool:
        """Return whether the shared cleanup deadline has passed."""
        return self.remaining() <= 0

    def remaining_timeout(self) -> float | None:
        """Return the remaining budget for git-lock recovery callbacks."""
        return self.remaining()


@contextmanager
def bounded_cleanup_alarm(
    budget: PublicationCleanupBudget,
) -> Iterator[PublicationCleanupBudget]:
    """Bound Python stalls during exception cleanup without touching drain attribution.

    Uses a one-shot SIGALRM only on the main thread when timers exist;
    elsewhere this is a no-op and cooperative git deadlines still apply.
    Never touches DrainTiming alarm fields so the original publication
    timeout attribution survives.
    """
    can_bound = (
        hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    )
    if not can_bound:
        yield budget
        return

    def _on_alarm(_signum: int, _frame: object) -> None:
        raise PublicationCleanupTimedOut(
            f"publication cleanup did not complete within {budget.timeout:.0f}s"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, _on_alarm)
    # Cap the alarm to the remaining budget so a near-exhausted budget
    # cannot grant a fresh full second.
    remaining = max(budget.remaining(), 1e-6)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield budget
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_delay, previous_interval = previous_timer
        # The drain alarm is already spent before exception cleanup starts,
        # so there is normally no previous timer to restore. Restore one
        # when it exists to preserve caller signal state.
        if previous_delay > 0:
            elapsed = max(0.0, budget.timeout - budget.remaining())
            restored = max(previous_delay - elapsed, 1e-6)
            signal.setitimer(signal.ITIMER_REAL, restored, previous_interval)
        elif previous_interval > 0:
            signal.setitimer(signal.ITIMER_REAL, 0, previous_interval)


def bounded_git_runner(
    base: GitRunner,
    budget: PublicationCleanupBudget,
) -> GitRunner:
    """Wrap *base* so every git call respects the shared cleanup deadline."""

    from sase.agents_sync import git as git_module

    def _run(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "agents_sync.git",
    ) -> subprocess.CompletedProcess[str]:
        remaining = budget.remaining()
        if remaining <= 0:
            return subprocess.CompletedProcess(
                args,
                128,
                "",
                "publication cleanup budget exhausted",
            )
        # The real runner can enforce the remaining budget cooperatively
        # (lock-retry remaining_timeout plus a capped subprocess timeout).
        # Injected fakes keep their behavior after the budget check above;
        # the outer SIGALRM backstop still bounds a stalled fake.
        if base is git_module.run_git:
            return git_module.run_git(
                cwd,
                args,
                network=network,
                op=op,
                remaining_timeout=budget.remaining_timeout,  # type: ignore[call-arg]
            )
        return base(cwd, args, network=network, op=op)

    return _run

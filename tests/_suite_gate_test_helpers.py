"""Shared builders for the suite-gate test modules.

Named ``_test_helpers`` rather than ``_helpers`` because the ``tests/_suite_gate*``
modules are the gate implementation itself; this module holds only test-side
construction helpers for them.
"""

from __future__ import annotations

from pathlib import Path

from tests._suite_gate_lease import WorkerTokenLease


ROOT = Path(__file__).resolve().parents[1]


def make_lease(
    directory: Path,
    *,
    budget: int = 1,
    timeout: float = 1,
    status_interval: float = 30,
    stale_timeout: float = 0.0,
    max_hold: float = 0.0,
    watchdog_interval: float = 0.0,
) -> WorkerTokenLease:
    """Return a fast-polling lease against ``directory``'s token pool."""
    return WorkerTokenLease(
        directory,
        budget,
        timeout,
        capacity_is_explicit=True,
        poll_interval=0.01,
        status_interval=status_interval,
        stale_timeout=stale_timeout,
        max_hold=max_hold,
        watchdog_interval=watchdog_interval,
    )

"""Environment inputs the worker-token gate is configured by.

Split out of :mod:`tests._suite_gate` so the rest of the family reads its
knobs from one place. Everything here is a name the operator can set or a
parse of one: the pool directory, the bounded timeouts, and the variables a
held lease exports to mark its descendants as already accounted for.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


_DEFAULT_TIMEOUT_SECONDS = 45 * 60
# A live holder that stops completing work (no progress heartbeat) is treated
# as wedged. Thirty minutes is longer than any legitimate single test in this
# suite and far shorter than the 27-hour scoped run that motivated the bound.
_DEFAULT_STALE_SECONDS = 30 * 60
# Absolute backstop even while heartbeats continue. A full suite is minutes;
# four hours covers a loaded host without letting one grant sit overnight.
_DEFAULT_MAX_HOLD_SECONDS = 4 * 60 * 60
_DEFAULT_WATCHDOG_SECONDS = 30.0

DISABLED_ENV = "SASE_TEST_GATE_DISABLED"
GOVERNED_ENV = "SASE_TEST_GATE_GOVERNED"
LEASE_ID_ENV = "SASE_TEST_GATE_LEASE_ID"
LEASE_PID_ENV = "SASE_TEST_GATE_LEASE_PID"
FDS_ENV = "SASE_TEST_GATE_FDS"
#: Every variable a held lease overwrites, and therefore every variable it
#: must restore on release.
LEASE_ENV_NAMES = (
    DISABLED_ENV,
    GOVERNED_ENV,
    LEASE_ID_ENV,
    LEASE_PID_ENV,
    FDS_ENV,
)


def gate_directory() -> Path:
    """Return the shared token-pool directory for the current UID."""
    configured = os.environ.get("SASE_TEST_GATE_DIR")
    if configured:
        return Path(configured)
    return Path(f"/tmp/sase-pytest-tokens-{os.getuid()}")


def gate_timeout() -> float:
    """Return the configured bounded acquisition timeout."""
    return non_negative_float_env("SASE_TEST_GATE_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)


def holder_stale_timeout() -> float:
    """Seconds without a progress heartbeat before a live holder is reclaimable.

    Zero disables stale-heartbeat reclaim. The waiter and the holder's
    watchdog both read this so tests can shrink the bound without changing
    the production default.
    """
    return non_negative_float_env("SASE_TEST_GATE_STALE", _DEFAULT_STALE_SECONDS)


def holder_max_hold() -> float:
    """Absolute age after which a live holder is reclaimable even if progressing.

    Zero disables the age cap. This is the backstop for a grant that keeps
    writing heartbeats but never finishes.
    """
    return non_negative_float_env("SASE_TEST_GATE_MAX_HOLD", _DEFAULT_MAX_HOLD_SECONDS)


def holder_watchdog_interval() -> float:
    """How often a holder checks its own grant for reclaim. Zero disables it."""
    return non_negative_float_env("SASE_TEST_GATE_WATCHDOG", _DEFAULT_WATCHDOG_SECONDS)


def positive_int(name: str, raw_value: str) -> int:
    """Parse ``raw_value`` as a positive integer, blaming ``name`` if it is not."""
    try:
        value = int(raw_value)
    except ValueError as error:
        raise pytest.UsageError(f"{name} must be a positive integer") from error
    if value < 1:
        raise pytest.UsageError(f"{name} must be a positive integer")
    return value


def non_negative_float_env(name: str, default: float) -> float:
    """Read ``name`` as a non-negative number, falling back to ``default``."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as error:
        raise pytest.UsageError(f"{name} must be a non-negative number") from error
    if value < 0:
        raise pytest.UsageError(f"{name} must be a non-negative number")
    return value

"""Usage-probe deadlines that stay meaningful under CPU contention.

An isolated probe starts a worker interpreter that imports sase, and the worker
then starts the fake CLI interpreter. On an idle host that costs about a second
of CPU. In the contention soak (26 xdist workers pinned to two CPUs) each process
gets roughly a thirteenth of a CPU, so start-up alone can take 10 s or more.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator

from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT

# Deadline for probes whose test asserts a classification (ok, unsupported,
# rate_limited, ...). There the deadline is a hang guard, not the behavior under
# test, so it must cover interpreter start-up on a starved host.
PROBE_HANG_GUARD_SECONDS = LOAD_TOLERANT_TIMEOUT


def hang_deadlines(first_seconds: float) -> Iterator[float]:
    """Yield deadlines for a test that hangs a fake CLI until the probe deadline.

    Such a test proves what happens to a fake child that is already running when
    the deadline expires, so the deadline must expire *after* the child starts.
    Under contention a short deadline can run out during interpreter start-up,
    before the child exists. That attempt missed the test's precondition; it did
    not fail its assertion. The caller asserts the timeout outcome on every
    attempt, then retries with the next, doubled deadline only when the child
    never appeared. The sequence stops at the hang guard, so a child that never
    starts still fails the test.
    """
    deadline = first_seconds
    while deadline < PROBE_HANG_GUARD_SECONDS:
        yield deadline
        deadline *= 2
    yield PROBE_HANG_GUARD_SECONDS


def pid_is_live(pid: int) -> bool:
    """Return True when *pid* still names a runnable (non-zombie) process.

    ``os.kill(pid, 0)`` succeeds for zombies, so a descendant that SIGKILL
    already ended still looks alive until init reaps it. Usage-probe tests
    that assert cleanup treat a zombie as gone: it cannot leak CPU or hold
    files, and the PID is only waiting for ``wait``.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    try:
        state = subprocess.check_output(
            ["ps", "-o", "stat=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return False
    return bool(state) and not state.startswith("Z")


def wait_until_reaped(pid: int, *, timeout: float = LOAD_TOLERANT_TIMEOUT) -> None:
    """Wait until *pid* is gone or a zombie.

    The hang guard covers init reaping and D-state delay under the
    two-CPU contention soak; it is not a speed assertion.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pid_is_live(pid):
        time.sleep(0.05)  # sase-test-wait: init reaps the killed descendant
    assert not pid_is_live(pid), f"pid {pid} still live after {timeout}s"


__all__ = [
    "PROBE_HANG_GUARD_SECONDS",
    "hang_deadlines",
    "pid_is_live",
    "wait_until_reaped",
]

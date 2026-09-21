"""Foreground lifecycle orchestration for the service host."""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Any

from sase.config.core import set_include_local_config
from sase.procs.oneshot import settle_orphaned_oneshots
from sase.service.control import ServiceHostLock
from sase.service.env import load_service_environment
from sase.service.host_reporting import write_current_host_status
from sase.service.state import clear_service_host

_STARTUP_LOCK_RETRY_SECONDS = 1.0
_STARTUP_LOCK_POLL_SECONDS = 0.02


def run_host(host: Any, reconcile_seconds: float) -> int:
    """Run a host until it receives a shutdown signal."""
    set_include_local_config(False)
    load_service_environment(override_existing=True)
    lock = _acquire_startup_lock()
    if lock is None:
        print("sase service run: service host is already running", file=sys.stderr)
        return 1
    try:
        lock.write_holder_pid()
        _install_signal_handlers(host)
        settle_orphaned_oneshots()
        host._record_heartbeat()
        host._reconcile_once()
        while host._running:
            host._nudge.wait(reconcile_seconds)
            host._nudge.clear()
            host._reconcile_once()
        host._stop_all_children()
        write_current_host_status(host)
        clear_service_host(os.getpid())
        return 0
    except KeyboardInterrupt:
        host._stop_all_children()
        clear_service_host(os.getpid())
        return 130
    finally:
        lock.release()


def _acquire_startup_lock() -> ServiceHostLock | None:
    """Take the host lifetime lock, tolerating momentary contention.

    A single nonblocking attempt cannot tell a live host from a status
    probe (or racing starter) that happens to hold the lock file at that
    instant, and the loser would falsely exit as "already running". A live
    host holds the lock for its whole lifetime, so retrying briefly keeps
    genuine convergence while riding out transient holders.
    """
    deadline = time.monotonic() + _STARTUP_LOCK_RETRY_SECONDS
    while True:
        lock = ServiceHostLock.acquire(blocking=False)
        if lock is not None:
            return lock
        if time.monotonic() >= deadline:
            return None
        time.sleep(_STARTUP_LOCK_POLL_SECONDS)


def _install_signal_handlers(host: Any) -> None:
    def shutdown(_signum: int, _frame: object) -> None:
        host._running = False
        host._nudge.set()

    def nudge(_signum: int, _frame: object) -> None:
        host._nudge.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, nudge)

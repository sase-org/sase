"""Host lifetime: lock convergence, racing starts, stale records, signals."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.service.control import (
    ServiceHostLock,
    _is_service_host_lock_held,
    _probe_service_host,
    nudge_service_host,
    start_service_host,
    stop_service_host,
)
from sase.service.host import _ServiceHost
from sase.service.host_lifecycle import run_host
from sase.service.state import (
    ServiceHostRecord,
    read_service_state,
    record_service_host,
)
from tests.service.service_host_scenario_helpers import (
    _compose,
    _layer_spec,
    _preserved_host_globals,
    _reaped_pid,
    _stub_host_spawn,
    _wait_for,
)


def test_concurrent_host_starts_converge_on_one_lifetime_lock_holder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two racing hosts converge: exactly one holds the lifetime lock."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SASE_SERVICE_ENV", raising=False)
    monkeypatch.setattr(
        "sase.service.host_state.load_service_config", lambda: _compose({})
    )
    # ``run_host`` installs process signal handlers, so every ``run_host``
    # call below runs on the main thread; the racing peer holds the real
    # lifetime lock from a worker thread.
    acquired = threading.Event()
    release = threading.Event()
    holder_outcome: list[bool] = []

    def _hold_lock() -> None:
        lock = ServiceHostLock.acquire(blocking=False)
        holder_outcome.append(lock is not None)
        acquired.set()
        assert release.wait(timeout=15)
        if lock is not None:
            lock.release()

    with _preserved_host_globals():
        holder = threading.Thread(target=_hold_lock, daemon=True)
        holder.start()
        assert acquired.wait(timeout=10)
        assert holder_outcome == [True]

        # The loser observes the held lock and exits without touching children.
        assert run_host(_ServiceHost(), 0.05) == 1
        assert _is_service_host_lock_held()

        release.set()
        holder.join(timeout=15)
        assert not holder.is_alive()
        assert not _is_service_host_lock_held()

        # With the lock free, a host starts, holds the lock alone, and stops.
        # The first acquires fail spuriously (simulating a status probe that
        # holds the lock file at that instant); the retry must ride them out.
        # A live host holds the lock continuously, so the loser path above
        # still converges.
        real_acquire = ServiceHostLock.acquire
        attempts: list[bool] = []

        def _flaky_acquire(cls: object, *, blocking: bool) -> ServiceHostLock | None:
            attempts.append(blocking)
            if len(attempts) <= 2:
                return None
            return real_acquire(blocking=blocking)

        monkeypatch.setattr(ServiceHostLock, "acquire", classmethod(_flaky_acquire))
        # The stopper waits on the heartbeat (a flock-free state read) so its
        # polling can never contend with the winner's exclusive acquire.
        started_before = time.time()

        def _fresh_heartbeat() -> bool:
            host_record = read_service_state().state.host
            return (
                host_record is not None
                and host_record.pid == os.getpid()
                and host_record.heartbeat_at >= started_before
            )

        def _stopper() -> None:
            try:
                assert _wait_for(_fresh_heartbeat, timeout=10)
                assert _is_service_host_lock_held()
                assert ServiceHostLock.acquire(blocking=False) is None
            finally:
                os.kill(os.getpid(), signal.SIGTERM)

        stopper = threading.Thread(target=_stopper, daemon=True)
        stopper.start()
        assert run_host(_ServiceHost(), 30.0) == 0
        stopper.join(timeout=15)
        assert not stopper.is_alive()
        assert len(attempts) >= 3

    assert not _is_service_host_lock_held()
    assert read_service_state().state.host is None


def test_racing_starts_serialize_behind_the_start_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two racing ``start_service_host`` calls spawn exactly one host."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    spawned: list[list[str]] = []
    _stub_host_spawn(monkeypatch, spawned)

    barrier = threading.Barrier(2)
    results: dict[int, object] = {}

    def _start(which: int) -> None:
        barrier.wait(timeout=10)
        results[which] = start_service_host(wait_seconds=10)

    workers = [
        threading.Thread(target=_start, args=(which,), daemon=True)
        for which in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    assert not any(worker.is_alive() for worker in workers)
    assert len(results) == 2

    outcomes = [results[which] for which in sorted(results)]
    assert all(outcome.ok for outcome in outcomes)  # type: ignore[union-attr]
    assert sorted(outcome.changed for outcome in outcomes) == [False, True]  # type: ignore[union-attr]
    assert {outcome.pid for outcome in outcomes} == {os.getpid()}  # type: ignore[union-attr]
    assert len(spawned) == 1
    assert spawned[0][-2:] == ["service", "run"]


def test_stale_host_record_and_lock_file_do_not_block_a_new_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A dead pid's lock text and host record do not block a fresh host."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    dead_pid = _reaped_pid()

    # A previous holder wrote its pid into the lock file, then died; the
    # flock died with it, so only the stale text remains.
    stale = ServiceHostLock.acquire(blocking=False)
    assert stale is not None
    stale.write_holder_pid(dead_pid)
    stale.release()

    now = time.time()
    record_service_host(
        ServiceHostRecord(
            pid=dead_pid,
            started_at=now,
            heartbeat_at=now,
            mode="foreground",
        )
    )

    probe = _probe_service_host()
    assert probe.record is not None and probe.record.pid == dead_pid
    assert probe.pid_alive is False
    assert probe.lock_held is False
    assert probe.running is False

    # A new host takes the lifetime lock, and stop/nudge see through the
    # stale record instead of signaling a dead pid.
    with ServiceHostLock.acquire(blocking=False) as lock:
        lock.write_holder_pid()
    stopped = stop_service_host()
    assert (stopped.ok, stopped.changed) == (True, False)
    assert stopped.message == "service host is not running"
    assert nudge_service_host() is False

    # Start proceeds to spawn instead of reporting "already running".
    spawned: list[list[str]] = []
    _stub_host_spawn(monkeypatch, spawned)
    started = start_service_host(wait_seconds=10)
    assert started.ok and started.changed
    assert started.pid == os.getpid()
    assert len(spawned) == 1


def test_host_signal_handling_stops_children_and_releases_the_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SIGUSR1 nudges an immediate reconcile; SIGTERM stops children cleanly."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SASE_SERVICE_ENV", raising=False)
    flag_path = tmp_path / "got-sigterm"
    trapping = (
        sys.executable,
        "-c",
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, "
        "lambda s, f: open(sys.argv[1], 'w').write('term')); "
        "time.sleep(30)",
        str(flag_path),
    )
    monkeypatch.setattr(
        "sase.service.host_state.load_service_config",
        lambda: _compose({"worker": _layer_spec(trapping)}),
    )
    settle_calls: list[int] = []
    import sase.service.host_lifecycle as host_lifecycle

    real_settle = host_lifecycle.settle_orphaned_oneshots

    def _recording_settle() -> list[object]:
        settled = real_settle()
        settle_calls.append(len(settled))
        return settled

    monkeypatch.setattr(
        "sase.service.host_lifecycle.settle_orphaned_oneshots", _recording_settle
    )

    host = _ServiceHost()
    reconciles = 0
    original_reconcile = host._reconcile_once

    def _counting_reconcile() -> None:
        nonlocal reconciles
        reconciles += 1
        original_reconcile()

    host._reconcile_once = _counting_reconcile  # type: ignore[method-assign]
    worker_pids: list[int] = []

    def _driver() -> None:
        try:
            assert _wait_for(lambda: reconciles >= 1, timeout=10)
            assert _wait_for(lambda: "worker" in host._children, timeout=10)
            worker_pids.append(host._children["worker"].process.pid)
            time.sleep(1.0)  # sase-test-wait: let the child install its SIGTERM trap
            os.kill(os.getpid(), signal.SIGUSR1)
            _wait_for(lambda: reconciles >= 2, timeout=10)
        finally:
            # Always release the main thread, even when an assert above fails.
            os.kill(os.getpid(), signal.SIGTERM)

    with _preserved_host_globals():
        driver = threading.Thread(target=_driver, daemon=True)
        driver.start()
        # A long cadence proves SIGUSR1 (not the timer) triggers the reconcile.
        assert run_host(host, 30.0) == 0
        driver.join(timeout=15)
        assert not driver.is_alive()

    assert reconciles >= 2
    assert settle_calls == [0]
    assert worker_pids and not is_process_running(worker_pids[0])
    # The child saw the configured SIGTERM (not just the SIGKILL fallback).
    assert flag_path.read_text(encoding="utf-8") == "term"
    assert not host._children
    assert not _is_service_host_lock_held()
    assert read_service_state().state.host is None

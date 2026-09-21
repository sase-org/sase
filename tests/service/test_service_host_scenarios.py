"""Scenario coverage for the foreground service-host runtime.

Each test drives the real ``_ServiceHost`` / ``ServiceHostLock`` code under
a temporary ``SASE_HOME`` with cheap real children (``python -c`` sleepers
and fail-fast exits). Config travels the real composition path
(``_compose_service_config`` over synthetic layers); only the layer-discovery
seam is stubbed. The platform lifecycle stays untouched: no test spawns
``sase service run`` or routes through the native unit.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.config.core import ConfigLayer
from sase.procs import (
    ACTIVE_PROC_STATUSES,
    COMMAND_PROC_KIND,
    TERMINAL_PROC_STATUSES,
    ProcReserve,
    ProcSupervisorClaim,
    claim_proc_supervisor,
    get_proc,
    reserve_proc,
)
from sase.procs.identity import supervisor_identity_token
from sase.procs.oneshot import settle_orphaned_oneshots
from sase.procs.service_meta import (
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)
from sase.service.config import ServiceConfigComposition, _compose_service_config
from sase.service.control import (
    ServiceHostLock,
    _is_service_host_lock_held,
    _probe_service_host,
    nudge_service_host,
    start_service_host,
    stop_service_host,
    utc_timestamp,
)
from sase.service.host import _ServiceHost
from sase.service.host_lifecycle import run_host
from sase.service.state import (
    ServiceHostRecord,
    clear_service_stop,
    read_service_state,
    record_service_host,
    record_service_stop,
)

_SLEEPER = (sys.executable, "-c", "import time; time.sleep(30)")
_FAIL_FAST = (sys.executable, "-c", "import sys; sys.exit(1)")


def _layer_spec(
    argv: tuple[str, ...],
    *,
    restart: str = "on-failure",
    stop_signal: str = "SIGTERM",
    stop_timeout: float = 0.5,
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "command": [str(part) for part in argv],
        "enabled": enabled,
        "restart": restart,
        "stop_signal": stop_signal,
        "stop_timeout": stop_timeout,
    }


def _compose(procs: dict[str, dict[str, object]]) -> ServiceConfigComposition:
    layer = ConfigLayer(
        name="user",
        path="/home/u/sase.yml",
        exists=True,
        list_strategy="concatenate",
        data={"service": {"procs": dict(procs)}},
    )
    return _compose_service_config([layer])


def _wait_for(predicate: Callable[[], bool], *, timeout: float = 15.0) -> bool:
    """Poll *predicate* until it holds or *timeout* expires."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)  # sase-test-wait: poll for child exit or proc-store state


@contextmanager
def _service_host(
    monkeypatch: pytest.MonkeyPatch,
    get_config: Callable[[], ServiceConfigComposition],
) -> Iterator[_ServiceHost]:
    """Yield a real host with stubbed config discovery; stop children on exit."""
    monkeypatch.setattr("sase.service.host.load_service_config", get_config)
    host = _ServiceHost()
    try:
        yield host
    finally:
        host._stop_all_children()


@contextmanager
def _preserved_host_globals() -> Iterator[None]:
    """Save and restore the process-global state ``run_host`` rewrites."""
    import sase.config.core as config_core

    saved_term = signal.getsignal(signal.SIGTERM)
    saved_int = signal.getsignal(signal.SIGINT)
    saved_usr1 = (
        signal.getsignal(signal.SIGUSR1) if hasattr(signal, "SIGUSR1") else None
    )
    saved_local = config_core._include_local_config
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, saved_term)
        signal.signal(signal.SIGINT, saved_int)
        if saved_usr1 is not None:
            signal.signal(signal.SIGUSR1, saved_usr1)
        from sase.config.core import set_include_local_config

        set_include_local_config(saved_local)


def _child_exited(host: _ServiceHost, name: str) -> bool:
    running = host._children.get(name)
    return running is not None and running.process.poll() is not None


def test_concurrent_host_starts_converge_on_one_lifetime_lock_holder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two racing hosts converge: exactly one holds the lifetime lock."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SASE_SERVICE_ENV", raising=False)
    monkeypatch.setattr("sase.service.host.load_service_config", lambda: _compose({}))
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


def _stub_host_spawn(monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]) -> None:
    """Stub the ``sase service run`` exec: record the spawn, publish a heartbeat."""

    def _fake_popen(argv: object, **kwargs: object) -> object:
        spawned.append([str(part) for part in argv])  # type: ignore[union-attr]
        now = time.time()
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(),
                started_at=now,
                heartbeat_at=now,
                mode="foreground",
            )
        )

        class _FakeChild:
            pid = os.getpid()

        return _FakeChild()

    monkeypatch.setattr(
        "sase.service.control._native_lifecycle_action", lambda _action: None
    )
    # Popen is looked up as an attribute of the shared subprocess module, so
    # the monkeypatch window must not overlap any real child spawn.
    monkeypatch.setattr("sase.service.control.subprocess.Popen", _fake_popen)


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


def _reaped_pid() -> int:
    """Return a pid that has exited and been reaped (stale by construction)."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    assert not is_process_running(child.pid)
    return child.pid


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
        "sase.service.host.load_service_config",
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


def test_host_config_reload_adds_stops_and_restarts_without_changing_the_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reloads add, remove, and restart entries while the host pid is stable."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"alpha": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "alpha" in host._children)
        alpha_pid = host._children["alpha"].process.pid
        assert read_service_state().state.host is not None
        assert read_service_state().state.host.pid == os.getpid()  # type: ignore[union-attr]

        # An added entry starts; the untouched entry keeps its pid.
        cell["composition"] = _compose(
            {
                "alpha": _layer_spec(_SLEEPER),
                "beta": _layer_spec(_SLEEPER),
            }
        )
        host._reconcile_once()
        assert _wait_for(lambda: "beta" in host._children)
        assert host._children["alpha"].process.pid == alpha_pid

        # A removed entry stops; a changed entry restarts with a new pid.
        changed = (
            sys.executable,
            "-c",
            "import time; time.sleep(31)",
        )
        cell["composition"] = _compose({"alpha": _layer_spec(changed)})
        host._reconcile_once()
        assert "beta" not in host._children
        assert "beta" not in host._pending
        assert host._children["alpha"].process.pid != alpha_pid
        assert not is_process_running(alpha_pid)

        # The host itself never changed across the reloads.
        assert read_service_state().state.host is not None
        assert read_service_state().state.host.pid == os.getpid()  # type: ignore[union-attr]


def test_stop_marker_racing_a_restart_settles_on_one_consistent_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stop racing a restart never yields two children or a torn state file."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"gamma": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "gamma" in host._children)
        first_pid = host._children["gamma"].process.pid

        # Stop marker plus changed entry in one reconcile: the stop wins and
        # no restart is scheduled behind it.
        record_service_stop("gamma", actor="pytest-host-scenarios")
        cell["composition"] = _compose(
            {
                "gamma": _layer_spec(
                    (sys.executable, "-c", "import time; time.sleep(31)")
                )
            }
        )
        host._reconcile_once()
        assert "gamma" not in host._children
        assert "gamma" not in host._pending
        assert not is_process_running(first_pid)

        # Clearing the stop relaunches exactly one child with the new command.
        clear_service_stop("gamma")
        host._reconcile_once()
        assert _wait_for(lambda: "gamma" in host._children)
        assert list(host._children) == ["gamma"]
        assert host._children["gamma"].process.pid != first_pid

        # A pending restart racing a stop is dropped, never launched.
        cell["composition"] = _compose({"delta": _layer_spec(_FAIL_FAST)})
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "delta"))
        host._observe_exits(cell["composition"], read_service_state())
        assert "delta" in host._pending
        record_service_stop("delta", actor="pytest-host-scenarios")
        pending = host._pending["delta"]
        pending.restart_at = time.time() - 1
        host._reconcile_desired(cell["composition"], read_service_state())
        assert "delta" not in host._children
        assert "delta" not in host._pending

        snapshot = read_service_state()
        assert "delta" in snapshot.state.stops
        assert "gamma" not in snapshot.state.stops


def test_crashing_child_backs_off_while_the_host_stays_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A fail-fast child restarts with growing backoff; the host keeps serving."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"epsilon": _layer_spec(_FAIL_FAST)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        delays: list[float] = []
        for _ in range(4):
            assert _wait_for(lambda: _child_exited(host, "epsilon"), timeout=15)
            host._observe_exits(cell["composition"], read_service_state())
            decision = host._restart_decisions["epsilon"]
            assert decision.action == "restart"
            assert decision.restart_at is not None
            delays.append(decision.delay_seconds)
            pending = host._pending.get("epsilon")
            assert pending is not None
            # Jump past the backoff instead of sleeping through it.
            pending.restart_at = time.time() - 1
            host._reconcile_desired(cell["composition"], read_service_state())
            assert "epsilon" in host._children

        assert delays == sorted(delays) and len(set(delays)) > 1
        final = host._restart_decisions["epsilon"]
        assert final.crash_loop is True
        assert final.history.consecutive_failures == 4
        assert host._running is True

        # Settle the relaunched child without forcing another restart, so the
        # crasher is deterministically parked in backoff below.
        assert _wait_for(lambda: _child_exited(host, "epsilon"), timeout=15)
        host._observe_exits(cell["composition"], read_service_state())
        assert "epsilon" in host._pending

        # The looping host still serves other entries: a healthy proc starts
        # while the crasher waits out its backoff.
        cell["composition"] = _compose(
            {
                "epsilon": _layer_spec(_FAIL_FAST),
                "zeta": _layer_spec(_SLEEPER),
            }
        )
        host._reconcile_once()
        assert _wait_for(lambda: "zeta" in host._children)
        assert "epsilon" in host._pending


def _reserve_oneshot_row(
    proc_id: str, tmp_path: Path, *, created_at: str | None = None
) -> str:
    return reserve_proc(
        ProcReserve(
            proc_id=proc_id,
            label=f"oneshot: {proc_id}",
            argv=["sh", "-c", "echo hi"],
            cwd=str(tmp_path),
            created_at=utc_timestamp() if created_at is None else created_at,
            log_path=str(tmp_path / f"{proc_id}.log"),
            request_fingerprint=f"fp-{proc_id}",
            reserved_by="pytest-host-scenarios",
            kind=COMMAND_PROC_KIND,
            origin=SERVICE_ONESHOT_ORIGIN,
            service=ProcServiceBlock(
                name=None,
                mode=SERVICE_PROC_MODE_ONESHOT,
                source=SERVICE_PROC_SOURCE_TRANSIENT,
            ),
        )
    ).proc.proc_id


def _claim_row(
    proc_id: str, *, supervisor_id: str, pid: int | None, pgid: int | None = None
) -> None:
    claim_proc_supervisor(
        ProcSupervisorClaim(
            proc_id=proc_id,
            supervisor_id=supervisor_id,
            claimed_at=utc_timestamp(),
            pid=pid,
            pgid=pgid,
        )
    )


def test_host_start_settles_orphaned_oneshots_without_relaunching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A leftover active oneshot settles terminally with unknown outcome."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    orphan_id = _reserve_oneshot_row("oneshot-orphan", tmp_path)
    _claim_row(orphan_id, supervisor_id="dead-boot:12345", pid=424242, pgid=424242)
    fresh_id = _reserve_oneshot_row("oneshot-fresh", tmp_path)
    alive_id = _reserve_oneshot_row("oneshot-alive", tmp_path)
    _claim_row(
        alive_id,
        supervisor_id=supervisor_identity_token(os.getpid()),
        pid=os.getpid(),
        pgid=os.getpgrp(),
    )
    for proc_id in (orphan_id, fresh_id, alive_id):
        assert get_proc(proc_id) is not None
        assert get_proc(proc_id).status in ACTIVE_PROC_STATUSES  # type: ignore[union-attr]

    settled = settle_orphaned_oneshots()

    assert {proc.proc_id for proc in settled} == {orphan_id}
    orphan = get_proc(orphan_id)
    assert orphan is not None and orphan.status in TERMINAL_PROC_STATUSES
    assert "unknown" in (orphan.message or "")
    # Settle-once: a second startup pass finds nothing to do.
    assert settle_orphaned_oneshots() == []

    # Rows with a live supervisor (or still inside the unclaimed grace
    # window) are left alone for their owner to finish.
    for proc_id in (fresh_id, alive_id):
        current = get_proc(proc_id)
        assert current is not None and current.status in ACTIVE_PROC_STATUSES

    # The host reconcile loop never picks the settled row back up.
    monkeypatch.setattr("sase.service.host.load_service_config", lambda: _compose({}))
    host = _ServiceHost()
    try:
        host._reconcile_once()
        assert not host._children
        assert not host._pending
        current = get_proc(orphan_id)
        assert current is not None and current.status in TERMINAL_PROC_STATUSES
    finally:
        host._stop_all_children()


def test_host_start_survives_a_oneshot_settle_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A proc-store error while settling oneshots must not stop the host."""
    import sase.service.host_lifecycle as host_lifecycle

    def _broken_settle() -> list[object]:
        raise RuntimeError("proc store unreadable")

    monkeypatch.setattr(
        "sase.service.host_lifecycle.settle_orphaned_oneshots", _broken_settle
    )

    host_lifecycle._settle_orphaned_oneshots_at_startup()

    assert "oneshot settle error: proc store unreadable" in capsys.readouterr().err

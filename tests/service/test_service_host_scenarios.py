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
from sase.service.restart import ServiceRestartHistory
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
    request_service_proc,
)
from sase.service.status import read_service_status

_SLEEPER = (sys.executable, "-c", "import time; time.sleep(30)")
_FAIL_FAST = (sys.executable, "-c", "import sys; sys.exit(1)")
_CLEAN_EXIT = (sys.executable, "-c", "import sys; sys.exit(0)")
_SLOW_FAIL = (
    sys.executable,
    "-c",
    "import time; time.sleep(1.5); sys.exit(1)",
)


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
    # These scenarios drive the real detached fallback, so they opt into the
    # isolated lifecycle override that the pytest guard otherwise blocks.
    monkeypatch.setenv("SASE_SERVICE_ALLOW_LIFECYCLE_IN_TESTS", "1")

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


def test_proc_restart_request_replaces_child_and_completes_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A restart request is a confirmed transition to a new pid."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"theta": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "theta" in host._children)
        old_pid = host._children["theta"].process.pid

        request_service_proc("theta", "restart", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert "theta" in host._children
        new_pid = host._children["theta"].process.pid
        assert new_pid != old_pid
        assert not is_process_running(old_pid)

        stored = read_service_state().state.requests["theta"]
        assert stored.generation == 1
        assert stored.completed_generation == 1
        assert stored.outcome == "restarted"
        assert stored.pid == new_pid

        # A second tick consumes nothing new: the pid is stable.
        host._reconcile_desired(cell["composition"], read_service_state())
        assert host._children["theta"].process.pid == new_pid
        assert read_service_state().state.requests["theta"].completed_generation == 1


def test_proc_start_request_launches_stopped_proc_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A start request on a stopped proc launches it and completes."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"iota": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "iota" in host._children)
        first_pid = host._children["iota"].process.pid

        record_service_stop("iota", actor="pytest-restartgen")
        host._reconcile_once()
        assert "iota" not in host._children
        assert not is_process_running(first_pid)

        request_service_proc("iota", "start", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert _wait_for(lambda: "iota" in host._children)
        assert host._children["iota"].process.pid != first_pid

        stored = read_service_state().state.requests["iota"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "started"
        assert stored.pid == host._children["iota"].process.pid


def test_proc_start_request_on_live_child_completes_already_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A start request for a live child launches nothing new."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"kappa": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "kappa" in host._children)
        live_pid = host._children["kappa"].process.pid

        request_service_proc("kappa", "start", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert host._children["kappa"].process.pid == live_pid

        stored = read_service_state().state.requests["kappa"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "already_running"
        assert stored.pid == live_pid


def test_proc_request_for_disabled_proc_completes_not_desired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A request for a disabled proc completes without launching."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"lambda": _layer_spec(_SLEEPER, enabled=False)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        request_service_proc("lambda", "start", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert "lambda" not in host._children

        stored = read_service_state().state.requests["lambda"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "not_desired"
        assert stored.error is not None and "disabled" in stored.error


def test_second_request_while_pending_is_consumed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two requests before one tick consume the latest generation once."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"mu": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "mu" in host._children)
        old_pid = host._children["mu"].process.pid

        request_service_proc("mu", "restart", actor="pytest-restartgen")
        request_service_proc("mu", "restart", actor="pytest-restartgen")
        assert read_service_state().state.requests["mu"].generation == 2

        host._reconcile_desired(cell["composition"], read_service_state())

        assert "mu" in host._children
        new_pid = host._children["mu"].process.pid
        assert new_pid != old_pid

        stored = read_service_state().state.requests["mu"]
        assert stored.generation == 2
        assert stored.completed_generation == 2
        assert stored.outcome == "restarted"

        # The completed request is never consumed again.
        host._reconcile_desired(cell["composition"], read_service_state())
        assert host._children["mu"].process.pid == new_pid


def test_config_outage_keeps_last_good_and_publishes_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A raising composition leaves children running and publishes the error."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"alpha": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "alpha" in host._children)
        alpha_pid = host._children["alpha"].process.pid
        baseline = read_service_status()
        assert baseline is not None
        assert baseline.host.error is None
        assert read_service_state().state.host is not None
        assert read_service_state().state.host.error is None  # type: ignore[union-attr]

        def _raise() -> ServiceConfigComposition:
            raise RuntimeError("boom config")

        monkeypatch.setattr("sase.service.host.load_service_config", _raise)
        host._reconcile_once()

        assert "alpha" in host._children
        assert host._children["alpha"].process.pid == alpha_pid
        assert is_process_running(alpha_pid)
        assert host._config_error is not None and "boom config" in host._config_error
        host_record = read_service_state().state.host
        assert host_record is not None
        assert host_record.error is not None and "boom config" in host_record.error
        snapshot = read_service_status()
        assert snapshot is not None
        assert snapshot.host.error is not None and "boom config" in snapshot.host.error
        assert snapshot.generated_at >= baseline.generated_at

        monkeypatch.setattr(
            "sase.service.host.load_service_config", lambda: cell["composition"]
        )
        host._reconcile_once()
        assert host._config_error is None
        assert host._last_good_config is not None
        recovered = read_service_state().state.host
        assert recovered is not None and recovered.error is None
        recovered_snapshot = read_service_status()
        assert recovered_snapshot is not None and recovered_snapshot.host.error is None
        assert host._children["alpha"].process.pid == alpha_pid


def test_exit_during_config_outage_settles_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A child that exits while the config raises is settled per its entry."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"epsilon": _layer_spec(_FAIL_FAST)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "epsilon"), timeout=15)

        def _raise() -> ServiceConfigComposition:
            raise RuntimeError("boom config during exit")

        monkeypatch.setattr("sase.service.host.load_service_config", _raise)
        host._reconcile_once()

        assert "epsilon" not in host._children
        assert "epsilon" in host._pending
        assert "epsilon" in host._last_exits
        assert host._pending["epsilon"].entry.name == "epsilon"
        assert host._config_error is not None
        assert "boom config during exit" in host._config_error
        snapshot = read_service_status()
        assert snapshot is not None
        assert snapshot.host.error is not None
        assert "boom config during exit" in snapshot.host.error

        host._pending["epsilon"].restart_at = time.time() - 1
        host._reconcile_once()
        assert _wait_for(lambda: "epsilon" in host._children, timeout=15)


def test_bad_config_at_startup_writes_degraded_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No last-good at startup still heartbeats and writes a fresh snapshot."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    def _raise() -> ServiceConfigComposition:
        raise RuntimeError("startup boom")

    with _service_host(monkeypatch, _raise) as host:
        assert not host._children
        host._reconcile_once()

        assert host._last_good_config is None
        assert host._config_error is not None
        assert "startup boom" in host._config_error
        host_record = read_service_state().state.host
        assert host_record is not None
        assert host_record.error is not None and "startup boom" in host_record.error
        snapshot = read_service_status()
        assert snapshot is not None
        assert snapshot.procs == ()
        assert snapshot.host.error is not None
        assert "startup boom" in snapshot.host.error


def test_on_failure_clean_exit_stays_down_with_single_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An on-failure proc that exits clean parks instead of relaunching."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"eta": _layer_spec(_CLEAN_EXIT)})
    }
    launches: list[str] = []
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        real_launch = host._launch

        def _counting_launch(entry: object, **kwargs: object) -> None:
            launches.append(entry.name)  # type: ignore[attr-defined]
            return real_launch(entry, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(host, "_launch", _counting_launch)
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "eta"), timeout=15)
        host._reconcile_once()

        assert "eta" not in host._children
        assert "eta" in host._given_up
        assert host._restart_decisions["eta"].action == "give_up"

        for _ in range(3):
            host._reconcile_once()
            assert "eta" not in host._children
            assert "eta" in host._given_up
        assert launches == ["eta"]


def test_never_policy_failure_stays_down_and_reports_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A never proc that fails parks and reads as exited with its last exit."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"theta_giveup": _layer_spec(_FAIL_FAST, restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "theta_giveup"), timeout=15)
        host._reconcile_once()

        assert "theta_giveup" not in host._children
        assert "theta_giveup" in host._given_up
        assert host._restart_decisions["theta_giveup"].action == "give_up"

        for _ in range(3):
            host._reconcile_once()
            assert "theta_giveup" not in host._children
        assert "theta_giveup" in host._given_up

        snapshot = read_service_status()
        assert snapshot is not None
        row = next(p for p in snapshot.procs if p.name == "theta_giveup")
        assert row.state == "exited", row.summary
        assert row.last_exit is not None and row.last_exit.exit_code == 1


def test_spawn_failure_under_never_stays_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A never proc that cannot spawn parks instead of retrying."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"badbin": _layer_spec(("no-such-sase-test-binary-xyz",), restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()

        assert "badbin" not in host._children
        assert "badbin" in host._given_up
        assert host._restart_decisions["badbin"].action == "give_up"

        for _ in range(3):
            host._reconcile_once()
            assert "badbin" not in host._children
        assert "badbin" in host._given_up


def test_explicit_start_revives_given_up_and_clears_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit start request relaunches a parked proc and clears it."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"iota_giveup": _layer_spec(_FAIL_FAST, restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "iota_giveup"), timeout=15)
        host._reconcile_once()
        assert "iota_giveup" in host._given_up

        request_service_proc("iota_giveup", "start", actor="pytest-giveup")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert "iota_giveup" not in host._given_up
        assert "iota_giveup" in host._children

        stored = read_service_state().state.requests["iota_giveup"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "started"


def test_signature_change_revives_given_up_without_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A new entry signature drops the parked record and relaunches."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"kappa_giveup": _layer_spec(_FAIL_FAST, restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "kappa_giveup"), timeout=15)
        host._reconcile_once()
        assert "kappa_giveup" in host._given_up

        cell["composition"] = _compose({"kappa_giveup": _layer_spec(_SLEEPER)})
        host._reconcile_once()

        assert "kappa_giveup" not in host._given_up
        assert _wait_for(lambda: "kappa_giveup" in host._children, timeout=15)


def test_crash_loop_notifies_once_per_episode_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failures notify once; aged failures stay crash-loop; a healthy run clears."""
    import sase.service.notifications as service_notifications

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"lambda_loop": _layer_spec(_SLOW_FAIL)})
    }
    seen: list[dict[str, object]] = []

    def _record(
        notification: object,
        *,
        plus_one_note: str | None = None,
        plus_one_timestamp: str | None = None,
        supersedes: str | None = None,
    ) -> object:
        seen.append(
            {
                "sender": notification.sender,  # type: ignore[attr-defined]
                "dedup_key": notification.dedup_key,  # type: ignore[attr-defined]
                "notes": list(notification.notes),  # type: ignore[attr-defined]
                "tags": list(notification.tags),  # type: ignore[attr-defined]
            }
        )

        class _Outcome:
            action = "created"

        return _Outcome()

    monkeypatch.setattr(service_notifications, "upsert_notification", _record)
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        for _ in range(3):
            assert _wait_for(lambda: _child_exited(host, "lambda_loop"), timeout=15)
            host._observe_exits(cell["composition"], read_service_state())
            pending = host._pending.get("lambda_loop")
            assert pending is not None
            # Jump past the backoff instead of sleeping through it.
            pending.restart_at = time.time() - 1
            host._reconcile_desired(cell["composition"], read_service_state())
            assert "lambda_loop" in host._children

        assert host._restart_decisions["lambda_loop"].crash_loop is True
        assert len(seen) == 1
        assert seen[0]["sender"] == "service"

        # Failures spaced past the backoff cap stay crash-loop without
        # notifying again: the sticky episode keeps alerting silently.
        running = host._children["lambda_loop"]
        now = time.time()
        running.restart_history = ServiceRestartHistory(
            started_at=running.restart_history.started_at,
            backoff_seconds=running.restart_history.backoff_seconds,
            consecutive_failures=3,
            recent_failures=(now - 200.0, now - 150.0, now - 130.0),
            alert_sent=True,
        )
        assert _wait_for(lambda: _child_exited(host, "lambda_loop"), timeout=15)
        host._observe_exits(cell["composition"], read_service_state())
        aged = host._restart_decisions["lambda_loop"]
        assert aged.action == "restart"
        assert aged.crash_loop is True
        assert aged.notify is False
        assert len(seen) == 1
        pending = host._pending.get("lambda_loop")
        assert pending is not None
        pending.restart_at = time.time() - 1
        host._reconcile_desired(cell["composition"], read_service_state())
        assert "lambda_loop" in host._children

        # A run that stays healthy past the threshold clears the episode.
        running = host._children["lambda_loop"]
        running.restart_history = ServiceRestartHistory(
            started_at=time.time() - 400.0,
            backoff_seconds=running.restart_history.backoff_seconds,
            consecutive_failures=running.restart_history.consecutive_failures,
            recent_failures=running.restart_history.recent_failures,
            alert_sent=True,
        )
        assert _wait_for(lambda: _child_exited(host, "lambda_loop"), timeout=15)
        host._observe_exits(cell["composition"], read_service_state())
        recovered = host._restart_decisions["lambda_loop"]
        assert recovered.action == "restart"
        assert recovered.crash_loop is False
        assert recovered.history.consecutive_failures == 1
        assert recovered.history.alert_sent is False
        assert len(seen) == 1


def test_give_up_notification_names_the_revive_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A parked desired proc upserts one service row with the revive command."""
    import sase.service.notifications as service_notifications

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"nu_giveup": _layer_spec(_FAIL_FAST, restart="never")})
    }
    seen: list[dict[str, object]] = []

    def _record(
        notification: object,
        *,
        plus_one_note: str | None = None,
        plus_one_timestamp: str | None = None,
        supersedes: str | None = None,
    ) -> object:
        seen.append(
            {
                "sender": notification.sender,  # type: ignore[attr-defined]
                "dedup_key": notification.dedup_key,  # type: ignore[attr-defined]
                "notes": list(notification.notes),  # type: ignore[attr-defined]
                "tags": list(notification.tags),  # type: ignore[attr-defined]
            }
        )

        class _Outcome:
            action = "created"

        return _Outcome()

    monkeypatch.setattr(service_notifications, "upsert_notification", _record)
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "nu_giveup"), timeout=15)
        host._reconcile_once()

        assert "nu_giveup" in host._given_up
        assert len(seen) == 1
        row = seen[0]
        assert row["sender"] == "service"
        assert "nu_giveup" in row["tags"]  # type: ignore[operator]
        notes = row["notes"]
        assert any("sase service proc start nu_giveup" in str(note) for note in notes)  # type: ignore[union-attr]
        assert any("Log:" in str(note) for note in notes)  # type: ignore[union-attr]

        # A second tick while parked notifies nothing new.
        host._reconcile_once()
        assert len(seen) == 1

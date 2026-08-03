from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = _ROOT / "tools" / "run_pytest"
_POOL_SIZE = 3
# Preserve the idle-host waits as floors, then scale the slow-host budgets from
# the measured time to launch and admit the initially granted children.
_ADMISSION_DEADLINE_FLOOR_SECONDS = 20.0
_ADMISSION_DEADLINE_STARTUP_MULTIPLIER = 8.0
_RELEASED_CHILD_EXIT_FLOOR_SECONDS = 60.0
_RELEASED_CHILD_EXIT_STARTUP_MULTIPLIER = 60.0
_SIGKILL_REAP_FLOOR_SECONDS = 10.0
_SIGKILL_REAP_STARTUP_MULTIPLIER = 4.0
_WAITING_PROBE_SECONDS = 0.5
_CHILD_GATE_TIMEOUT_MARGIN_SECONDS = 30.0
_CHILD_SUITE = """\
from __future__ import annotations

import os
import socket


def test_hold_worker_token_until_released() -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as coordinator:
        coordinator.connect(os.environ["SASE_TEST_GATE_INTEGRATION_SOCKET"])
        run_id = os.environ["SASE_TEST_GATE_INTEGRATION_RUN_ID"]
        coordinator.sendall(f"{run_id}\\n".encode())
        assert coordinator.recv(1) == b"R"
"""


@dataclass(frozen=True)
class _SuiteGateBudgets:
    startup_seconds: float
    admission_deadline: float
    released_child_exit_timeout: float
    sigkill_reap_timeout: float
    child_gate_timeout: float


def _budgets_from_startup(startup_seconds: float) -> _SuiteGateBudgets:
    admission_deadline = max(
        _ADMISSION_DEADLINE_FLOOR_SECONDS,
        _ADMISSION_DEADLINE_STARTUP_MULTIPLIER * startup_seconds,
    )
    sigkill_reap_timeout = max(
        _SIGKILL_REAP_FLOOR_SECONDS,
        _SIGKILL_REAP_STARTUP_MULTIPLIER * startup_seconds,
    )
    # Build the waiter environment after calibration so the child gate timeout
    # covers its intentional pre-release wait as well as the admission deadline.
    child_gate_timeout = (
        _WAITING_PROBE_SECONDS
        + sigkill_reap_timeout
        + admission_deadline
        + _CHILD_GATE_TIMEOUT_MARGIN_SECONDS
    )
    return _SuiteGateBudgets(
        startup_seconds=startup_seconds,
        admission_deadline=admission_deadline,
        released_child_exit_timeout=max(
            _RELEASED_CHILD_EXIT_FLOOR_SECONDS,
            _RELEASED_CHILD_EXIT_STARTUP_MULTIPLIER * startup_seconds,
        ),
        sigkill_reap_timeout=sigkill_reap_timeout,
        child_gate_timeout=child_gate_timeout,
    )


def _child_environment(
    pool_dir: Path, socket_path: Path, run_id: str, *, gate_timeout: float | None
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("PYTEST_XDIST_"):
            environment.pop(name, None)
    for name in (
        "PYTEST_XDIST_WORKER",
        "SASE_PYTEST_WORKERS",
        "SASE_TEST_GATE_DISABLED",
        "SASE_TEST_GATE_GOVERNED",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "SASE_PYTEST_WORKER_CEILING": "1",
            "SASE_PYTEST_WORKER_FLOOR": "1",
            "SASE_TEST_GATE_DIR": str(pool_dir),
            "SASE_TEST_GATE_INTEGRATION_RUN_ID": run_id,
            "SASE_TEST_GATE_INTEGRATION_SOCKET": str(socket_path),
            "SASE_TEST_GATE_SLOTS": str(_POOL_SIZE),
            # Nested child runs should not share the outer full suite's scratch
            # root. Its stale-run reaper and temp leak guard can otherwise make
            # child pytest teardown depend on unrelated concurrent suite work.
            "SASE_PYTEST_TMPDIR": str(pool_dir.parent / "child-pytest" / run_id),
        }
    )
    if gate_timeout is not None:
        environment["SASE_TEST_GATE_TIMEOUT"] = f"{gate_timeout:g}"
    return environment


def _start_scaled_suite(
    suite_path: Path,
    pool_dir: Path,
    socket_path: Path,
    run_id: str,
    *,
    gate_timeout: float | None = None,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(_RUNNER), "fast", str(suite_path), "-q"],
        cwd=_ROOT,
        env=_child_environment(
            pool_dir,
            socket_path,
            run_id,
            gate_timeout=gate_timeout,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _accept_run(coordinator: socket.socket) -> tuple[str, socket.socket]:
    connection, _address = coordinator.accept()
    run_id = connection.recv(128).decode().strip()
    return run_id, connection


def _active_grants(pool_dir: Path, controller_pids: set[int]) -> dict[int, int]:
    grants: dict[int, int] = {}
    for token_path in pool_dir.glob("token-*.lock"):
        metadata = json.loads(token_path.read_text(encoding="utf-8"))
        pid = int(metadata["pid"])
        if pid in controller_pids:
            grants[pid] = int(metadata["granted"])
    return grants


def _kill_process_group(process: subprocess.Popen[str], *, reap_timeout: float) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=reap_timeout)


def _assert_success(
    run_id: str,
    process: subprocess.Popen[str],
    *,
    pool_dir: Path,
    controller_pids: set[int],
    budgets: _SuiteGateBudgets,
) -> None:
    try:
        stdout, stderr = process.communicate(
            timeout=budgets.released_child_exit_timeout
        )
    except subprocess.TimeoutExpired as error:
        grants_before_kill = _active_grants(pool_dir, controller_pids)
        _kill_process_group(process, reap_timeout=budgets.sigkill_reap_timeout)
        stdout, stderr = process.communicate()
        grants_after_kill = _active_grants(pool_dir, controller_pids)
        raise AssertionError(
            f"run_id: {run_id}\n"
            f"pid: {process.pid}\n"
            f"timed out after {error.timeout:g}s waiting for child exit\n"
            f"startup_seconds: {budgets.startup_seconds:.3f}\n"
            "budgets: "
            f"admission={budgets.admission_deadline:g}s, "
            f"exit={budgets.released_child_exit_timeout:g}s, "
            f"reap={budgets.sigkill_reap_timeout:g}s, "
            f"child_gate={budgets.child_gate_timeout:g}s\n"
            f"active grants before SIGKILL: {grants_before_kill}\n"
            f"active grants after SIGKILL: {grants_after_kill}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        ) from error
    assert process.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"


def test_scaled_suite_runs_share_capacity_and_release_after_sigkill(
    tmp_path: Path,
) -> None:
    pool_dir = tmp_path / "tokens"
    suite_path = tmp_path / "test_scaled_suite.py"
    suite_path.write_text(_CHILD_SUITE, encoding="utf-8")
    # Keep the AF_UNIX address out of the long per-test directory: Linux caps
    # sockaddr_un paths at 108 bytes, and pytest's run counter can push the
    # otherwise valid scratch path over that limit.
    socket_path = tmp_path.parent / f"sg-{os.getpid()}.sock"
    socket_path.unlink(missing_ok=True)
    coordinator = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    coordinator.bind(str(socket_path))
    coordinator.listen(_POOL_SIZE + 1)
    coordinator.settimeout(_ADMISSION_DEADLINE_FLOOR_SECONDS)

    processes: dict[str, subprocess.Popen[str]] = {}
    connections: dict[str, socket.socket] = {}
    initial_run_ids = {f"run-{index}" for index in range(_POOL_SIZE)}
    try:
        startup_started = time.monotonic()
        for run_id in sorted(initial_run_ids):
            processes[run_id] = _start_scaled_suite(
                suite_path, pool_dir, socket_path, run_id
            )

        for _index in range(_POOL_SIZE):
            run_id, connection = _accept_run(coordinator)
            connections[run_id] = connection

        budgets = _budgets_from_startup(time.monotonic() - startup_started)
        assert set(connections) == initial_run_ids
        controller_pids = {process.pid for process in processes.values()}
        grants = _active_grants(pool_dir, controller_pids)
        assert grants == dict.fromkeys(controller_pids, 1)
        assert sum(grants.values()) == _POOL_SIZE

        waiter_id = "waiter"
        waiter = _start_scaled_suite(
            suite_path,
            pool_dir,
            socket_path,
            waiter_id,
            gate_timeout=budgets.child_gate_timeout,
        )
        processes[waiter_id] = waiter
        coordinator.settimeout(_WAITING_PROBE_SECONDS)
        with pytest.raises(TimeoutError):
            coordinator.accept()

        killed_id = min(initial_run_ids)
        killed = processes[killed_id]
        _kill_process_group(killed, reap_timeout=budgets.sigkill_reap_timeout)
        assert killed.returncode == -signal.SIGKILL

        coordinator.settimeout(budgets.admission_deadline)
        admitted_id, admitted_connection = _accept_run(coordinator)
        connections[admitted_id] = admitted_connection
        assert admitted_id == waiter_id
        surviving_pids = {
            process.pid for run_id, process in processes.items() if run_id != killed_id
        }
        grants = _active_grants(pool_dir, surviving_pids)
        assert grants == dict.fromkeys(surviving_pids, 1)
        assert sum(grants.values()) == _POOL_SIZE

        for run_id, connection in connections.items():
            if run_id != killed_id:
                connection.sendall(b"R")
        for run_id, process in processes.items():
            if run_id != killed_id:
                _assert_success(
                    run_id,
                    process,
                    pool_dir=pool_dir,
                    controller_pids=surviving_pids,
                    budgets=budgets,
                )
    finally:
        for connection in connections.values():
            connection.close()
        for process in processes.values():
            _kill_process_group(
                process,
                reap_timeout=_SIGKILL_REAP_FLOOR_SECONDS,
            )
        coordinator.close()
        socket_path.unlink(missing_ok=True)

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = _ROOT / "tools" / "run_pytest"
_POOL_SIZE = 3
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


def _child_environment(
    pool_dir: Path, socket_path: Path, run_id: str
) -> dict[str, str]:
    environment = os.environ.copy()
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
            "SASE_TEST_GATE_TIMEOUT": "15",
        }
    )
    return environment


def _start_scaled_suite(
    suite_path: Path, pool_dir: Path, socket_path: Path, run_id: str
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(_RUNNER), "fast", str(suite_path), "-q"],
        cwd=_ROOT,
        env=_child_environment(pool_dir, socket_path, run_id),
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


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def _assert_success(process: subprocess.Popen[str]) -> None:
    stdout, stderr = process.communicate(timeout=60)
    assert process.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"


def test_scaled_suite_runs_share_capacity_and_release_after_sigkill(
    tmp_path: Path,
) -> None:
    pool_dir = tmp_path / "tokens"
    suite_path = tmp_path / "test_scaled_suite.py"
    suite_path.write_text(_CHILD_SUITE, encoding="utf-8")
    socket_path = tmp_path / "coordinator.sock"
    coordinator = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    coordinator.bind(str(socket_path))
    coordinator.listen(_POOL_SIZE + 1)
    coordinator.settimeout(20)

    processes: dict[str, subprocess.Popen[str]] = {}
    connections: dict[str, socket.socket] = {}
    initial_run_ids = {f"run-{index}" for index in range(_POOL_SIZE)}
    try:
        for run_id in sorted(initial_run_ids):
            processes[run_id] = _start_scaled_suite(
                suite_path, pool_dir, socket_path, run_id
            )

        for _index in range(_POOL_SIZE):
            run_id, connection = _accept_run(coordinator)
            connections[run_id] = connection

        assert set(connections) == initial_run_ids
        controller_pids = {process.pid for process in processes.values()}
        grants = _active_grants(pool_dir, controller_pids)
        assert grants == dict.fromkeys(controller_pids, 1)
        assert sum(grants.values()) == _POOL_SIZE

        waiter_id = "waiter"
        waiter = _start_scaled_suite(suite_path, pool_dir, socket_path, waiter_id)
        processes[waiter_id] = waiter
        coordinator.settimeout(0.5)
        with pytest.raises(TimeoutError):
            coordinator.accept()

        killed_id = min(initial_run_ids)
        killed = processes[killed_id]
        _kill_process_group(killed)
        assert killed.returncode == -signal.SIGKILL

        coordinator.settimeout(20)
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
                _assert_success(process)
    finally:
        for connection in connections.values():
            connection.close()
        for process in processes.values():
            _kill_process_group(process)
        coordinator.close()

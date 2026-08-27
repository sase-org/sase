from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests._suite_gate_lease import WorkerTokenLease
from tests._test_selection_gear import (
    REFUSED_TOKENS_UNAVAILABLE,
    SCOPED_WORKER_FLOOR,
)
from tests._test_selection_timings import TIMINGS_SCHEMA, recording_host


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


_SCOPED_CONFTEST = """\
from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests._suite_gate import configure_suite_gate, unconfigure_suite_gate


def pytest_configure(config: pytest.Config) -> None:
    configure_suite_gate(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    unconfigure_suite_gate(config)
"""
_SCOPED_FILLER_COUNT = 9


def _build_scoped_repo(root: Path) -> None:
    """Lay out a miniature repository the real runner can select tests in.

    The runner resolves its own ``REPO_ROOT`` from ``__file__``, so the runner
    and the modules it imports are *copied*, never symlinked.
    """
    (root / "tools").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "src" / "pkg").mkdir(parents=True)

    shutil.copy(_RUNNER, root / "tools" / "run_pytest")
    for module in (
        "_contention.py",
        "_suite_gate.py",
        "_suite_gate_budget.py",
        "_suite_gate_env.py",
        "_suite_gate_holders.py",
        "_suite_gate_lease.py",
        "_suite_gate_messages.py",
        "_suite_gate_pool.py",
        "_suite_gate_progress.py",
        "_test_cost.py",
        "_test_cost_budgets.py",
        "_test_cost_plugin.py",
        "_test_cost_plugin_patches.py",
        "_test_cost_records.py",
        "_test_cost_report.py",
        "_test_selection.py",
        "_test_selection_changes.py",
        "_test_selection_contexts.py",
        "_test_selection_gear.py",
        "_test_selection_graph.py",
        "_test_selection_health.py",
        "_test_selection_health_correlation.py",
        "_test_selection_health_records.py",
        "_test_selection_health_report.py",
        "_test_selection_health_store.py",
        "_test_selection_manifest.py",
        "_test_selection_report.py",
        "_test_selection_rules.py",
        "_test_selection_timings.py",
        "_test_selection_timings_plugin.py",
        "_test_shards.py",
    ):
        shutil.copy(_ROOT / "tests" / module, root / "tests" / module)

    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text(_SCOPED_CONFTEST, encoding="utf-8")
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "thing.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_thing.py").write_text(
        "from pkg import thing\n\n\ndef test_value() -> None:\n"
        "    assert thing.VALUE == 1\n",
        encoding="utf-8",
    )
    # Filler keeps the selection well under the default 25% escalation ratio, so
    # the run under test is a genuine scoped run rather than an escalation.
    for index in range(_SCOPED_FILLER_COUNT):
        (root / "tests" / f"test_filler_{index}.py").write_text(
            "def test_filler() -> None:\n    assert True\n", encoding="utf-8"
        )

    _git(root, "init", "-q")
    _git(root, "config", "user.email", "gate@example.invalid")
    _git(root, "config", "user.name", "Suite Gate")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    # An uncommitted edit is the change set the selector walks from.
    (root / "src" / "pkg" / "thing.py").write_text("VALUE = 1  # edited\n", "utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _miniature_pool_environment(
    root: Path,
    pool_dir: Path,
    *,
    slots: int = 1,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("PYTEST_"):
            environment.pop(name, None)
    for name in (
        "SASE_PYTEST_WORKERS",
        "SASE_TEST_GATE_DISABLED",
        "SASE_TEST_GATE_GOVERNED",
        "SASE_TEST_SELECTION_DEPTH",
        "SASE_TEST_SELECTION_MAX_RATIO",
        "SASE_TEST_SELECTION_MAX_SERIAL_SECONDS",
        "SASE_TEST_SELECTION_SCOPED_WORKER_CEILING",
        "SASE_TEST_SELECTION_TIMINGS_DIR",
        "SASE_TEST_SELECTION_TIMINGS_DISABLED",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "SASE_CHECK_BASE": "HEAD",
            # Keep the runner's selection-health records inside the miniature
            # repo instead of the developer's real ``~/.sase`` store.
            "SASE_HOME": str(root / "sase-home"),
            "SASE_PYTEST_TMPDIR": str(root / "scratch"),
            "SASE_TEST_GATE_DIR": str(pool_dir),
            "SASE_TEST_GATE_SLOTS": str(slots),
            # Zero seconds turns any acquisition attempt into an immediate,
            # loud failure instead of a 45-minute queue.
            "SASE_TEST_GATE_TIMEOUT": "0",
        }
    )
    environment.update(extra or {})
    return environment


def _run_miniature_runner(
    root: Path,
    pool_dir: Path,
    mode: str,
    *,
    slots: int = 1,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "tools" / "run_pytest"), mode, "-q"],
        cwd=root,
        env=_miniature_pool_environment(root, pool_dir, slots=slots, extra=extra),
        capture_output=True,
        text=True,
    )


def _over_budget_environment(root: Path) -> dict[str, str]:
    """Price the miniature repo's one real test above the serial budget.

    The gear only ever sees a selection ``RULE_SERIAL_BUDGET_EXCEEDED``
    rejected, so reaching it end to end means giving the selector a duration
    table and a budget the table's answer exceeds.
    """
    directory = root / "timings"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "20260806T000000Z-1.json").write_text(
        json.dumps(
            {
                "schema": TIMINGS_SCHEMA,
                "recorded_at": "2026-08-06T00:00:00+00:00",
                "host": recording_host(),
                "mode": "fast",
                "worker_count": 1,
                "file_count": 1,
                "durations": {"tests/test_thing.py": 900.0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "SASE_TEST_SELECTION_TIMINGS_DIR": str(directory),
        "SASE_TEST_SELECTION_MAX_SERIAL_SECONDS": "10",
    }


def _scoped_manifest(root: Path) -> dict[str, Any]:
    return json.loads(
        (root / ".pytest_cache" / "sase-selection" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_scoped_run_takes_no_token_while_the_pool_is_exhausted(
    tmp_path: Path,
) -> None:
    """The property this whole lane exists to deliver: no queueing, ever."""
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    holder = WorkerTokenLease(
        directory=pool_dir, budget=1, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(1, 1, exact=True)
    try:
        scoped = _run_miniature_runner(root, pool_dir, "scoped")
        # The control: the same exhausted pool genuinely blocks a governed run,
        # so the scoped success above cannot be a mis-configured pool.
        governed = _run_miniature_runner(root, pool_dir, "fast")
    finally:
        holder.release()

    assert scoped.returncode == 0, f"stdout:\n{scoped.stdout}\nstderr:\n{scoped.stderr}"
    assert "selected 1 of 10 test files" in scoped.stderr
    assert "1 passed" in scoped.stdout
    # Every live grant still belongs to this process: the scoped run took none.
    assert set(_active_grants(pool_dir, {os.getpid()})) == {os.getpid()}
    assert {
        int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        for path in pool_dir.glob("token-*.lock")
    } == {os.getpid()}
    assert governed.returncode != 0
    assert "worker token" in (governed.stdout + governed.stderr).lower()

    manifest = _scoped_manifest(root)
    assert manifest["escalated"] is False
    assert manifest["selected"] == ["tests/test_thing.py"]
    assert manifest["outcome"] == "passed"
    assert manifest["duration"] > 0
    # Nothing escalated, so the gear was never offered anything and the
    # manifest says nothing about it.
    assert "gear" not in manifest


def test_ungoverned_bypass_is_bounded_by_the_host_budget(tmp_path: Path) -> None:
    """The incident, end to end, and the route that replaces it.

    `SASE_TEST_GATE_DISABLED=1` still means "take no tokens and never queue".
    It no longer means "take the whole machine": the pool cannot see this run,
    so its width is the one thing that must stay inside the budget.
    """
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)
    bypass = {
        "SASE_PYTEST_WORKERS": "4",
        "SASE_TEST_GATE_DISABLED": "1",
        # The miniature repo carries the runner's imports, not the full lane's
        # in-pytest failure recorder.
        "SASE_TEST_SELECTION_HEALTH_DISABLED": "1",
    }

    over_budget = _run_miniature_runner(root, pool_dir, "fast", slots=1, extra=bypass)

    assert over_budget.returncode != 0
    refusal = over_budget.stdout + over_budget.stderr
    assert "Requested 4 pytest worker tokens" in refusal
    assert "SASE_TEST_GATE_SLOTS" in refusal

    # The supported route for a genuinely wide run: enlarge the pool where
    # concurrent runs can see it. The pool is held to its capacity throughout,
    # which is what proves the bypass still never queues.
    holder = WorkerTokenLease(
        directory=pool_dir, budget=4, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(4, 4, exact=True)
    try:
        widened = _run_miniature_runner(root, pool_dir, "fast", slots=4, extra=bypass)
    finally:
        holder.release()

    assert widened.returncode == 0, (
        f"stdout:\n{widened.stdout}\nstderr:\n{widened.stderr}"
    )
    assert "suite gate bypassed: running 4 ungoverned workers" in widened.stderr
    assert "SASE_TEST_GATE_SLOTS" in widened.stderr
    assert "bringing up nodes" in widened.stdout
    # Every token in the pool is still the one this process took.
    assert {
        int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        for path in pool_dir.glob("token-*.lock")
    } == {os.getpid()}


def test_over_budget_selection_runs_at_a_leased_width_and_releases_it(
    tmp_path: Path,
) -> None:
    """The middle gear, end to end: leased workers instead of the full suite."""
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    scoped = _run_miniature_runner(
        root, pool_dir, "scoped", slots=4, extra=_over_budget_environment(root)
    )

    assert scoped.returncode == 0, f"stdout:\n{scoped.stdout}\nstderr:\n{scoped.stderr}"
    assert "middle gear: running the over-budget selection at 4 worker(s)" in (
        scoped.stderr
    )
    assert "escalating to the governed full test lane" not in scoped.stderr
    # The selection ran, and it ran wide: 10 filler files would have run too if
    # this had escalated.
    assert "1 passed" in scoped.stdout
    # xdist only announces nodes when it has some: proof the run was parallel.
    assert "bringing up nodes" in scoped.stdout

    manifest = _scoped_manifest(root)
    assert "serial-budget-exceeded" in manifest["rules_fired"]
    # The rule that sent the run to the gear stays on the record: it is why
    # the third gear engaged, not something the gear undid.
    assert manifest["escalated"] is False
    assert manifest["selected"] == ["tests/test_thing.py"]
    assert manifest["outcome"] == "passed"
    assert manifest["gear"] == {
        "granted": True,
        "worker_count": 4,
        "ceiling": 4,
        "floor": SCOPED_WORKER_FLOOR,
        "reason": None,
    }

    # The lease outlived the run and no longer: the whole pool is free again.
    reclaimed = WorkerTokenLease(
        directory=pool_dir, budget=4, timeout=0.0, capacity_is_explicit=True
    )
    assert reclaimed.try_acquire(4, 4) == 4
    reclaimed.release()


def test_over_budget_selection_escalates_rather_than_queueing_for_a_lease(
    tmp_path: Path,
) -> None:
    """A refused gear is an escalation, never a wait."""
    root = tmp_path / "repo"
    pool_dir = tmp_path / "tokens"
    _build_scoped_repo(root)

    holder = WorkerTokenLease(
        directory=pool_dir, budget=1, timeout=0.0, capacity_is_explicit=True
    )
    holder.acquire(1, 1, exact=True)
    started = time.monotonic()
    try:
        scoped = _run_miniature_runner(
            root, pool_dir, "scoped", slots=1, extra=_over_budget_environment(root)
        )
    finally:
        holder.release()
    elapsed = time.monotonic() - started

    assert "middle gear: no bounded lease (tokens-unavailable)" in scoped.stderr
    assert "escalating to the governed full test lane" in scoped.stderr
    # It escalated into an exhausted pool, whose zero-second timeout fails the
    # run loudly. That is the pre-existing escalation contract; what this test
    # pins is that the gear did not wait to get there.
    assert scoped.returncode != 0
    assert elapsed < _ADMISSION_DEADLINE_FLOOR_SECONDS
    # The holder's token was never taken from it.
    assert {
        int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        for path in pool_dir.glob("token-*.lock")
    } == {os.getpid()}

    manifest = _scoped_manifest(root)
    assert manifest["escalated"] is True
    assert manifest["selected"] == []
    assert manifest["outcome"] == "escalated"
    assert manifest["gear"] == {
        "granted": False,
        "worker_count": None,
        "ceiling": 4,
        "floor": SCOPED_WORKER_FLOOR,
        "reason": REFUSED_TOKENS_UNAVAILABLE,
    }


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

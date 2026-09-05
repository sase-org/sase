from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests._suite_gate_budget import automatic_worker_range
from tests._suite_gate_test_helpers import ROOT, make_lease


pytestmark = pytest.mark.contract


def test_floor_acquisition_grows_greedily_and_records_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_LEASE_ID", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_LEASE_PID", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_FDS", raising=False)
    lease = make_lease(tmp_path, budget=6)

    assert lease.acquire(2, 4) == 4
    assert lease.granted == 4
    assert os.environ["SASE_TEST_GATE_DISABLED"] == "1"
    assert os.environ["SASE_TEST_GATE_GOVERNED"] == "1"
    assert all(not os.get_inheritable(fd) for fd in lease.file_descriptors)

    metadata = json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))
    assert metadata["pid"] == os.getpid()
    assert metadata["budget"] == 6
    assert metadata["requested_floor"] == 2
    assert metadata["requested_ceiling"] == 4
    assert metadata["granted"] == 4
    assert metadata["heartbeat"] == metadata["started"]
    assert metadata["progress"] == 0
    assert metadata["lease_id"]
    assert os.environ["SASE_TEST_GATE_LEASE_ID"] == metadata["lease_id"]
    assert os.environ["SASE_TEST_GATE_LEASE_PID"] == str(os.getpid())

    lease.make_inheritable()
    assert all(os.get_inheritable(fd) for fd in lease.file_descriptors)
    lease.release()
    assert "SASE_TEST_GATE_DISABLED" not in os.environ
    assert "SASE_TEST_GATE_GOVERNED" not in os.environ
    assert "SASE_TEST_GATE_LEASE_ID" not in os.environ
    assert "SASE_TEST_GATE_LEASE_PID" not in os.environ
    assert "SASE_TEST_GATE_FDS" not in os.environ


def test_release_restores_inherited_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "parent-disabled")
    monkeypatch.setenv("SASE_TEST_GATE_GOVERNED", "parent-governed")
    lease = make_lease(tmp_path)

    lease.acquire(1, 1, exact=True)
    lease.release()

    assert os.environ["SASE_TEST_GATE_DISABLED"] == "parent-disabled"
    assert os.environ["SASE_TEST_GATE_GOVERNED"] == "parent-governed"


def test_scaled_leases_share_capacity_without_exceeding_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    first = make_lease(tmp_path, budget=6)
    second = make_lease(tmp_path, budget=6)

    assert first.acquire(2, 4) == 4
    assert second.acquire(2, 4) == 2
    assert first.granted + second.granted == 6

    first.release()
    second.release()


def test_default_automatic_range_keeps_room_for_a_peer_full_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    first = make_lease(tmp_path, budget=32)
    second = make_lease(tmp_path, budget=32)

    floor, ceiling = automatic_worker_range(32)
    assert (floor, ceiling) == (4, 14)
    assert first.acquire(floor, ceiling) == 14
    assert second.acquire(floor, ceiling) == 14

    try:
        assert first.granted + second.granted == 28
        spare = make_lease(tmp_path, budget=32)
        assert spare.try_acquire(4, 4) == 4
        spare.release()
    finally:
        second.release()
        first.release()


def test_simultaneous_leases_never_exceed_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    start = threading.Barrier(6)
    release = threading.Event()
    state_lock = threading.Lock()
    active_tokens = 0
    maximum_active_tokens = 0

    def _hold_tokens() -> None:
        nonlocal active_tokens, maximum_active_tokens
        lease = make_lease(tmp_path, budget=4, timeout=2)
        start.wait()
        grant = lease.acquire(1, 2)
        with state_lock:
            active_tokens += grant
            maximum_active_tokens = max(maximum_active_tokens, active_tokens)
            if maximum_active_tokens == 4:
                release.set()
        deadline = time.monotonic() + 1.0
        try:
            while not release.wait(0.01):  # sase-test-wait: suite-token overlap poll
                if time.monotonic() >= deadline:
                    break
        finally:
            with state_lock:
                active_tokens -= grant
            lease.release()

    threads = [threading.Thread(target=_hold_tokens) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum_active_tokens == 4
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)


def test_conflicting_explicit_capacity_fails_while_pool_is_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = make_lease(tmp_path, budget=4)
    holder.acquire(1, 1, exact=True)

    try:
        with pytest.raises(
            pytest.UsageError, match="SASE_TEST_GATE_SLOTS.*active pool"
        ):
            make_lease(tmp_path, budget=5).acquire(1, 1, exact=True)
    finally:
        holder.release()


def test_partial_attempt_rolls_back_instead_of_hoarding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = make_lease(tmp_path, budget=5)
    contender = make_lease(tmp_path, budget=5, timeout=0)
    replacement = make_lease(tmp_path, budget=5)
    holder.acquire(4, 4, exact=True)

    with pytest.raises(pytest.UsageError):
        contender.acquire(2, 2, exact=True)

    assert replacement.acquire(1, 1, exact=True) == 1
    holder.release()
    replacement.release()


def test_exact_request_larger_than_pool_fails_actionably(tmp_path: Path) -> None:
    with pytest.raises(pytest.UsageError) as error:
        make_lease(tmp_path, budget=3).acquire(4, 4, exact=True)

    message = str(error.value)
    assert "Requested 4 pytest worker tokens" in message
    assert "SASE_TEST_GATE_SLOTS" in message
    assert "SASE_PYTEST_WORKERS/-n" in message


def test_wait_and_timeout_deduplicate_holder_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = make_lease(tmp_path, budget=4)
    holder.acquire(4, 4, exact=True)

    try:
        with pytest.raises(pytest.UsageError) as error:
            make_lease(tmp_path, budget=4, timeout=0.02, status_interval=0).acquire(
                2, 2, exact=True
            )
    finally:
        holder.release()

    status = capsys.readouterr().err
    message = str(error.value)
    assert "2 worker tokens" in message
    assert "4 tokens: pid" in message
    assert f"pid {os.getpid()}" in status
    assert "heartbeat" in message
    assert "SASE_TEST_GATE_TIMEOUT" in message
    assert "SASE_TEST_GATE_STALE" in message
    assert "SASE_TEST_GATE_DISABLED=1" in message


def test_waiter_is_admitted_promptly_after_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    first = make_lease(tmp_path, budget=2)
    second = make_lease(tmp_path, budget=2)
    acquired = threading.Event()
    first.acquire(2, 2, exact=True)

    def _acquire_second() -> None:
        second.acquire(2, 2, exact=True)
        acquired.set()

    thread = threading.Thread(target=_acquire_second)
    thread.start()
    try:
        assert not acquired.wait(timeout=0.05)
        first.release()
        assert acquired.wait(timeout=1)
    finally:
        first.release()
        second.release()
        thread.join(timeout=1)


def test_tokens_are_reacquirable_after_exec_holder_is_sigkilled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "from tests._suite_gate_lease import WorkerTokenLease",
            "lease = WorkerTokenLease(Path(sys.argv[1]), 3, 5, "
            "capacity_is_explicit=True)",
            "lease.acquire(3, 3, exact=True)",
            "lease.make_inheritable()",
            "code = \"import time; print('ready', flush=True); time.sleep(60)\"",
            "os.execv(sys.executable, [sys.executable, '-c', code])",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        process.send_signal(signal.SIGKILL)
        assert process.wait(timeout=5) == -signal.SIGKILL

        replacement = make_lease(tmp_path, budget=3)
        assert replacement.acquire(3, 3, exact=True) == 3
        replacement.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._suite_gate import record_lease_progress
from tests._suite_gate_holders import holder_reclaim_reason
from tests._suite_gate_test_helpers import ROOT, make_lease


pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    ("started", "heartbeat", "now", "stale", "max_hold", "expected"),
    [
        (0.0, 0.0, 10.0, 30.0, 100.0, None),
        (0.0, 0.0, 30.0, 30.0, 100.0, "stale-heartbeat"),
        (0.0, 29.0, 30.0, 30.0, 100.0, None),
        (0.0, 29.0, 100.0, 30.0, 90.0, "max-hold"),
        (0.0, 0.0, 30.0, 0.0, 100.0, None),
        (0.0, 0.0, 100.0, 30.0, 0.0, "stale-heartbeat"),
        (0.0, 0.0, 100.0, 0.0, 0.0, None),
    ],
)
def test_holder_reclaim_reason_bounds(
    started: float,
    heartbeat: float,
    now: float,
    stale: float,
    max_hold: float,
    expected: str | None,
) -> None:
    metadata = json.dumps(
        {
            "argv": "tools/run_pytest scoped",
            "granted": 14,
            "heartbeat": heartbeat,
            "lease_id": "1-0",
            "pid": 1,
            "started": started,
        }
    )

    assert (
        holder_reclaim_reason(metadata, now=now, stale=stale, max_hold=max_hold)
        == expected
    )


def test_holder_reclaim_reason_uses_started_when_heartbeat_missing() -> None:
    metadata = json.dumps(
        {"argv": "pytest", "lease_id": "1-0", "pid": 1, "started": 0.0}
    )

    assert (
        holder_reclaim_reason(metadata, now=30.0, stale=30.0, max_hold=0.0)
        == "stale-heartbeat"
    )
    assert holder_reclaim_reason("not-json", stale=1.0, max_hold=1.0) is None


def test_progress_updates_sidecar_and_token_heartbeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("SASE_TEST_GATE_GOVERNED", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))
    lease = make_lease(tmp_path, budget=1)
    lease.acquire(1, 1, exact=True)
    try:
        before = json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))
        record_lease_progress("session")
        after = json.loads((tmp_path / "token-000.lock").read_text(encoding="utf-8"))
        sidecar = json.loads(
            (tmp_path / f"lease-{before['lease_id']}.progress").read_text(
                encoding="utf-8"
            )
        )
    finally:
        lease.release()

    assert after["heartbeat"] >= before["heartbeat"]
    assert after["progress"] == 1
    assert sidecar["event"] == "session"
    assert sidecar["progress"] == 1
    assert not (tmp_path / f"lease-{before['lease_id']}.progress").exists()


def test_timeout_message_flags_a_stale_holder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = make_lease(tmp_path, budget=2)
    holder.acquire(2, 2, exact=True)
    past = time.time() - 10
    for path in tmp_path.glob("token-*.lock"):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        parsed["started"] = past
        parsed["heartbeat"] = past
        path.write_text(json.dumps(parsed) + "\n", encoding="utf-8")

    try:
        with pytest.raises(pytest.UsageError) as error:
            make_lease(
                tmp_path, budget=2, timeout=0.02, status_interval=0, stale_timeout=1.0
            ).acquire(2, 2, exact=True)
    finally:
        holder.release()

    assert "stale-heartbeat" in str(error.value)
    assert "heartbeat" in str(error.value)


def test_waiter_reclaims_stale_live_holder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from tests._suite_gate_lease import WorkerTokenLease",
            "lease = WorkerTokenLease(Path(sys.argv[1]), 2, 5, "
            "capacity_is_explicit=True, watchdog_interval=0.0)",
            "lease.acquire(2, 2, exact=True)",
            "print('ready', flush=True)",
            "time.sleep(60)",
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
        time.sleep(0.12)  # sase-test-wait: exceed the waiter's stale bound
        waiter = make_lease(tmp_path, budget=2, timeout=5, stale_timeout=0.05)
        assert waiter.acquire(2, 2, exact=True) == 2
        waiter.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode != 0


def test_watchdog_releases_a_stale_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from tests._suite_gate_lease import WorkerTokenLease",
            "lease = WorkerTokenLease(Path(sys.argv[1]), 1, 5, "
            "capacity_is_explicit=True, stale_timeout=0.05, "
            "watchdog_interval=0.05, max_hold=0.0)",
            "lease.acquire(1, 1, exact=True)",
            "print('ready', flush=True)",
            "time.sleep(60)",
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
        waiter = make_lease(tmp_path, budget=1, timeout=5, stale_timeout=0.0)
        assert waiter.acquire(1, 1, exact=True) == 1
        waiter.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_fresh_heartbeat_is_not_reclaimed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import os, sys, time",
            "from pathlib import Path",
            "from tests._suite_gate import record_lease_progress",
            "from tests._suite_gate_lease import WorkerTokenLease",
            "os.environ.pop('PYTEST_XDIST_WORKER', None)",
            "os.environ['SASE_TEST_GATE_DIR'] = sys.argv[1]",
            "lease = WorkerTokenLease(Path(sys.argv[1]), 1, 5, "
            "capacity_is_explicit=True, watchdog_interval=0.0)",
            "lease.acquire(1, 1, exact=True)",
            "print('ready', flush=True)",
            "deadline = time.monotonic() + 2",
            "while time.monotonic() < deadline:",
            "    record_lease_progress('session')",
            "    time.sleep(0.02)",
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
        with pytest.raises(pytest.UsageError, match="heartbeat"):
            make_lease(tmp_path, budget=1, timeout=0.35, stale_timeout=0.2).acquire(
                1, 1, exact=True
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_max_hold_reclaims_even_with_fresh_heartbeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import os, sys, time",
            "from pathlib import Path",
            "from tests._suite_gate import record_lease_progress",
            "from tests._suite_gate_lease import WorkerTokenLease",
            "os.environ.pop('PYTEST_XDIST_WORKER', None)",
            "os.environ['SASE_TEST_GATE_DIR'] = sys.argv[1]",
            "lease = WorkerTokenLease(Path(sys.argv[1]), 1, 5, "
            "capacity_is_explicit=True, watchdog_interval=0.0)",
            "lease.acquire(1, 1, exact=True)",
            "print('ready', flush=True)",
            "deadline = time.monotonic() + 5",
            "while time.monotonic() < deadline:",
            "    record_lease_progress('session')",
            "    time.sleep(0.02)",
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
        time.sleep(0.12)  # sase-test-wait: exceed the waiter's max-hold bound
        waiter = make_lease(
            tmp_path, budget=1, timeout=5, stale_timeout=60.0, max_hold=0.05
        )
        assert waiter.acquire(1, 1, exact=True) == 1
        waiter.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

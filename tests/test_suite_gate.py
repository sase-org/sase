from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from tests._suite_gate import (
    SuiteGate,
    configure_suite_gate,
    unconfigure_suite_gate,
)


_ROOT = Path(__file__).resolve().parents[1]


def _config(numprocesses: object) -> pytest.Config:
    return cast(
        pytest.Config,
        SimpleNamespace(option=SimpleNamespace(numprocesses=numprocesses)),
    )


def _gate(
    directory: Path,
    *,
    slots: int = 1,
    timeout: float = 1,
    status_interval: float = 30,
) -> SuiteGate:
    return SuiteGate(
        directory,
        slots,
        timeout,
        poll_interval=0.01,
        status_interval=status_interval,
    )


def test_acquire_release_cycle_and_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    gate = _gate(tmp_path)

    gate.acquire()

    metadata = json.loads((tmp_path / "slot-0.lock").read_text(encoding="utf-8"))
    assert metadata["pid"] == os.getpid()
    assert metadata["argv"]
    assert metadata["started"] <= time.time()
    assert os.environ["SASE_TEST_GATE_DISABLED"] == "1"

    gate.release()
    assert "SASE_TEST_GATE_DISABLED" not in os.environ

    second_gate = _gate(tmp_path)
    second_gate.acquire()
    second_gate.release()


def test_extra_acquirer_waits_until_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    first_gate = _gate(tmp_path)
    second_gate = _gate(tmp_path)
    acquired = threading.Event()
    first_gate.acquire()

    def _acquire_second_gate() -> None:
        second_gate.acquire()
        acquired.set()

    thread = threading.Thread(target=_acquire_second_gate)
    thread.start()
    try:
        assert not acquired.wait(timeout=0.05)
        first_gate.release()
        assert acquired.wait(timeout=1)
    finally:
        first_gate.release()
        second_gate.release()
        thread.join(timeout=1)


def test_timeout_reports_holder_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = _gate(tmp_path)
    holder.acquire()

    try:
        with pytest.raises(pytest.UsageError) as error:
            _gate(tmp_path, timeout=0.02).acquire()
    finally:
        holder.release()

    message = str(error.value)
    assert f"pid {os.getpid()}" in message
    assert "SASE_TEST_GATE_TIMEOUT" in message
    assert "SASE_TEST_GATE_SLOTS" in message
    assert "SASE_TEST_GATE_DISABLED=1" in message


def test_wait_status_reports_holder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    holder = _gate(tmp_path)
    holder.acquire()

    try:
        with pytest.raises(pytest.UsageError):
            _gate(tmp_path, timeout=0.02, status_interval=0).acquire()
    finally:
        holder.release()

    assert f"pid {os.getpid()}" in capsys.readouterr().err


def test_configure_acquires_for_parallel_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_TEST_GATE_SLOTS", "1")
    monkeypatch.setenv("SASE_TEST_GATE_TIMEOUT", "0")
    config = _config(2)

    configure_suite_gate(config)

    assert (tmp_path / "slot-0.lock").exists()
    assert os.environ["SASE_TEST_GATE_DISABLED"] == "1"
    unconfigure_suite_gate(config)
    assert "SASE_TEST_GATE_DISABLED" not in os.environ


def test_configure_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_TEST_GATE_DISABLED", "1")
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))

    configure_suite_gate(_config(2))

    assert not (tmp_path / "slot-0.lock").exists()


def test_configure_skips_xdist_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))

    configure_suite_gate(_config(2))

    assert not (tmp_path / "slot-0.lock").exists()


@pytest.mark.parametrize("numprocesses", [None, 0, 1, "0", "1"])
def test_configure_skips_serial_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, numprocesses: object
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv("SASE_TEST_GATE_DIR", str(tmp_path))

    configure_suite_gate(_config(numprocesses))

    assert not (tmp_path / "slot-0.lock").exists()


def test_slot_is_reacquirable_after_holder_is_sigkilled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SASE_TEST_GATE_DISABLED", raising=False)
    script = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from tests._suite_gate import SuiteGate",
            "gate = SuiteGate(Path(sys.argv[1]), 1, 5)",
            "gate.acquire()",
            "print('ready', flush=True)",
            "time.sleep(60)",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        process.send_signal(signal.SIGKILL)
        assert process.wait(timeout=5) == -signal.SIGKILL

        replacement = _gate(tmp_path)
        replacement.acquire()
        replacement.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

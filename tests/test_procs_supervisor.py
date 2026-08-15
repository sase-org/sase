"""Crash-boundary tests for the detached proc-shell supervisor."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.procs import (
    get_proc,
    kill_proc,
    read_proc_log_tail,
    submit_proc,
    wait_for_proc,
)


def test_supervisor_is_reparented_away_from_the_starter(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Reparent",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)
    assert running.pid is not None
    assert _ppid(running.pid) != os.getpid()
    kill_proc(proc.proc_id)
    wait_for_proc(proc.proc_id, timeout=15)


def test_starter_exit_does_not_kill_a_released_proc(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    marker = tmp_path / "alive"
    script = tmp_path / "starter.py"
    script.write_text(
        "\n".join(
            [
                "import os, sys, time",
                "from pathlib import Path",
                "from sase.procs import submit_proc",
                f"os.environ['SASE_HOME'] = {str(tmp_path / 'home')!r}",
                "proc = submit_proc(",
                "    [sys.executable, '-c', 'import time; time.sleep(8)'],",
                "    label='Orphan-proof',",
                f"    cwd={str(tmp_path)!r},",
                "    origin='test',",
                ")",
                f"Path({str(tmp_path / 'proc_id')!r}).write_text(proc.proc_id)",
            ]
        ),
        encoding="utf-8",
    )
    starter = os.spawnv(os.P_NOWAIT, sys.executable, [sys.executable, str(script)])
    proc_id_path = tmp_path / "proc_id"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not proc_id_path.exists():
        time.sleep(0.05)  # sase-test-wait: poll starter-written proc id
    assert proc_id_path.exists()
    _wait_for_process_exit(starter)

    proc_id = proc_id_path.read_text(encoding="utf-8")
    running = _wait_for_running(proc_id)
    assert running.pid is not None
    assert is_process_running(running.pid)
    marker.write_text("ok", encoding="utf-8")
    finished = wait_for_proc(proc_id, timeout=15)
    assert finished.status == "success"


def test_invalid_utf8_and_quiet_commands_settle(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    noisy = submit_proc(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'ok\\xff\\n'); sys.stdout.buffer.flush()",
        ],
        label="Binary",
        cwd=tmp_path,
        origin="test",
    )
    quiet = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(0.2)"],
        label="Quiet",
        cwd=tmp_path,
        origin="test",
    )
    noisy_done = wait_for_proc(noisy.proc_id, timeout=15)
    quiet_done = wait_for_proc(quiet.proc_id, timeout=15)

    assert noisy_done.status == "success"
    log = read_proc_log_tail(noisy.proc_id, 10, log_path=noisy.log_path)
    assert "ok" in log
    assert quiet_done.status == "success"


def test_process_group_kill_reaps_grandchildren_and_resistant_children(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    grandchild_pid = tmp_path / "gpid"
    proc = submit_proc(
        [
            sys.executable,
            "-c",
            (
                "import os, signal, time, pathlib, sys\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "child = os.fork()\n"
                "if child == 0:\n"
                "    time.sleep(30)\n"
                "    raise SystemExit(0)\n"
                f"pathlib.Path({str(grandchild_pid)!r}).write_text(str(child))\n"
                "time.sleep(30)\n"
            ),
        ],
        label="Group",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not grandchild_pid.exists():
        time.sleep(0.05)  # sase-test-wait: poll grandchild pid file
    gpid = int(grandchild_pid.read_text(encoding="utf-8"))
    assert is_process_running(gpid)

    killed = kill_proc(proc.proc_id)
    wait_for_proc(proc.proc_id, timeout=20)

    assert killed.status == "killed"
    _wait_for_process_exit(gpid)
    if running.pid is not None:
        _wait_for_process_exit(running.pid)


def test_pid_reuse_is_not_treated_as_a_live_supervisor(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from sase.procs import reconcile_running_procs
    from sase.procs.models import Proc
    from sase.procs.store import append_proc

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    reused = Proc(
        proc_id="reusedshell1",
        label="reuse",
        kind="command",
        status="running",
        lifecycle="proc-shell",
        command=["true"],
        argv=["true"],
        cwd=str(tmp_path),
        origin="test",
        created_at="2026-07-25T12:00:00Z",
        log_path=str(tmp_path / "reusedshell1.log"),
        request_fingerprint="sha256:reuse",
        reserved_by="test",
        supervisor_id="ffffeeee-dead-beef-0000-111122223333:1",
        pid=os.getpid(),
    )
    append_proc(reused)
    reconciled = reconcile_running_procs()
    current = get_proc(reused.proc_id)
    assert current is not None
    assert current.proc_id in {item.proc_id for item in reconciled}
    assert current.status == "error"


def _wait_for_running(proc_id: str) -> Any:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        proc = get_proc(proc_id)
        assert proc is not None
        if proc.status == "running":
            return proc
        if proc.status not in {"pending", "running"}:
            pytest.fail(f"proc became {proc.status} before it was observed running")
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail("proc did not enter running state")


def _wait_for_process_exit(pid: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail(f"process {pid} did not exit")


def _ppid(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    raise AssertionError(f"no PPid for {pid}")

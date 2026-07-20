"""Tests for axe lifecycle locking."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from sase.axe.lock import AxeLifecycleLock, clear_lock_holder_pid, read_lock_holder_pid


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    state_dir.mkdir(parents=True, exist_ok=True)
    with patch("sase.axe.state.axe_state_dir", return_value=state_dir):
        yield state_dir


def test_lifecycle_lock_is_exclusive(temp_state_dir: Path) -> None:
    first = AxeLifecycleLock.acquire(blocking=False)
    assert first is not None
    try:
        assert AxeLifecycleLock.acquire(blocking=False) is None
    finally:
        first.release()

    second = AxeLifecycleLock.acquire(blocking=False)
    assert second is not None
    second.release()


def test_stale_lock_file_does_not_block_acquisition(temp_state_dir: Path) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("stale")

    lock = AxeLifecycleLock.acquire(blocking=False)
    assert lock is not None
    lock.release()


def test_lifecycle_lock_records_holder_pid(temp_state_dir: Path) -> None:
    lock = AxeLifecycleLock.acquire(blocking=False)
    assert lock is not None
    try:
        lock.write_holder_pid()
        assert read_lock_holder_pid() == os.getpid()

        lock.clear_holder_pid()
        assert read_lock_holder_pid() is None
    finally:
        lock.release()

    assert read_lock_holder_pid() is None


def test_lifecycle_lock_prefers_external_proc_holder(
    temp_state_dir: Path,
) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("24680")

    with (
        patch("sase.axe.lock._find_proc_lock_holder_pid", return_value=13579),
        patch("sase.ace.hooks.processes.is_process_running", return_value=False),
    ):
        assert read_lock_holder_pid() == 13579


def test_lifecycle_lock_prefers_live_recorded_daemon_over_proc_holder(
    temp_state_dir: Path,
) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("24680")

    def is_running(pid: int) -> bool:
        return pid == 24680

    with (
        patch("sase.axe.lock._find_proc_lock_holder_pid", return_value=13579),
        patch("sase.ace.hooks.processes.is_process_running", side_effect=is_running),
    ):
        assert read_lock_holder_pid() == 24680


def test_lifecycle_lock_uses_recorded_pid_when_proc_holder_is_current_process(
    temp_state_dir: Path,
) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("24680")

    with (
        patch("sase.axe.lock._find_proc_lock_holder_pid", return_value=os.getpid()),
        patch("sase.ace.hooks.processes.is_process_running", return_value=False),
    ):
        assert read_lock_holder_pid() == 24680


def test_lifecycle_lock_handoff_reports_recorded_child_pid(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    lock = AxeLifecycleLock.acquire(blocking=False)
    assert lock is not None
    handed_off = False
    proc: subprocess.Popen[str] | None = None
    child_code = "\n".join(
        [
            "import os",
            "import sys",
            "import time",
            "fd = int(sys.argv[1])",
            "pid = os.getpid()",
            "os.lseek(fd, 0, os.SEEK_SET)",
            "os.ftruncate(fd, 0)",
            "os.write(fd, (str(pid) + '\\n').encode())",
            "os.fsync(fd)",
            "print(pid, flush=True)",
            "time.sleep(30)",
        ]
    )
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", child_code, str(lock.fd)],
            pass_fds=(lock.fd,),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line, proc.stderr.read() if proc.stderr is not None else ""
        child_pid = int(line)

        lock.close_after_handoff()
        handed_off = True

        assert read_lock_holder_pid() == child_pid
        assert read_lock_holder_pid() != os.getpid()
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        if not handed_off:
            lock.release()


def test_clear_lock_holder_pid_without_lock(temp_state_dir: Path) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("12345")

    clear_lock_holder_pid()

    assert path.read_text() == ""

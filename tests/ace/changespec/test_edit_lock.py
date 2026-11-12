"""Tests for edit lock functions."""

import fcntl
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import threading
import time

import pytest

from sase.ace.patch import locking
from sase.ace.changespec.locking import (
    LockTimeoutError,
    acquire_edit_lock,
    changespec_lock as legacy_changespec_lock,  # legacy compatibility alias
    is_edit_locked,
    release_edit_lock,
    wait_for_edit_lock_release,
)


def test_acquire_creates_lock_file(tmp_path: Path) -> None:
    """Verify .edit_lock is created with current PID."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        lock_file = f"{project_file}.edit_lock"
        assert os.path.exists(lock_file)
        with open(lock_file) as lf:
            pid, start_token = lf.read().splitlines()
        assert pid == str(os.getpid())
        assert start_token
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_release_removes_lock_file(tmp_path: Path) -> None:
    """Verify release removes the .edit_lock file."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        assert os.path.exists(f"{project_file}.edit_lock")
        release_edit_lock(project_file)
        assert not os.path.exists(f"{project_file}.edit_lock")
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_is_edit_locked_returns_true_for_active_lock(tmp_path: Path) -> None:
    """Active lock (current PID) returns True."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        assert is_edit_locked(project_file) is True
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_is_edit_locked_cleans_stale_lock(tmp_path: Path) -> None:
    """Dead PID lock is removed and returns False."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    lock_file = f"{project_file}.edit_lock"
    try:
        # Write a PID that doesn't exist (use a very high PID)
        with open(lock_file, "w") as lf:
            lf.write("999999999")
        assert is_edit_locked(project_file) is False
        assert not os.path.exists(lock_file)
    finally:
        os.unlink(project_file)
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


def test_acquire_reclaims_lock_with_recycled_pid_token(tmp_path: Path) -> None:
    """An alive PID with a different process-start token is stale."""
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    Path(lock_file).write_text(f"{os.getpid()}\nold-process-incarnation\n")
    try:
        acquire_edit_lock(project_file)
        assert is_edit_locked(project_file)
        assert Path(lock_file).read_text().splitlines()[0] == str(os.getpid())
    finally:
        release_edit_lock(project_file)


def test_acquire_reclaims_malformed_edit_lock(tmp_path: Path) -> None:
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    Path(lock_file).write_text("not-a-pid\n")
    try:
        acquire_edit_lock(project_file)
        assert Path(lock_file).read_text().splitlines()[0] == str(os.getpid())
    finally:
        release_edit_lock(project_file)


def test_concurrent_edit_lock_acquisition_has_one_owner(tmp_path: Path) -> None:
    project_file = str(tmp_path / "test.sase")
    Path(project_file).touch()
    start = threading.Barrier(3)
    release = threading.Event()
    busy = threading.Event()
    outcomes: list[str] = []

    def contender() -> None:
        start.wait()
        try:
            acquire_edit_lock(project_file)
        except FileExistsError:
            outcomes.append("busy")
            busy.set()
            return
        outcomes.append("owner")
        release.wait(timeout=5)
        release_edit_lock(project_file)

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    assert busy.wait(timeout=2)
    release.set()
    for thread in threads:
        thread.join(timeout=2)
    assert sorted(outcomes) == ["busy", "owner"]


def test_patch_lock_timeout_preserves_error_and_closes_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.lock"
    Path(project_file).touch()
    held_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    original_open = locking.os.open
    patch_lock_fds: list[int] = []

    def capture_open(
        path: str, flags: int, mode: int = 0o777, **kwargs: int | None
    ) -> int:
        fd = original_open(path, flags, mode, **kwargs)
        if path == lock_file:
            patch_lock_fds.append(fd)
        return fd

    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(locking.os, "open", capture_open)
            with pytest.raises(LockTimeoutError):
                with locking.patch_lock(project_file, timeout=0, poll_interval=0):
                    pytest.fail("lock unexpectedly acquired")
            assert len(patch_lock_fds) == 1
            with pytest.raises(OSError):
                os.fstat(patch_lock_fds[0])
    finally:
        os.close(held_fd)


def test_is_edit_locked_returns_false_when_no_lock(tmp_path: Path) -> None:
    """No lock file returns False."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    try:
        assert is_edit_locked(project_file) is False
    finally:
        os.unlink(project_file)


def test_release_nonexistent_lock_is_noop() -> None:
    """Releasing a lock that doesn't exist doesn't raise."""
    release_edit_lock("/tmp/nonexistent_project_file.sase")


# --- wait_for_edit_lock_release tests ---


def test_wait_returns_immediately_when_unlocked(tmp_path: Path) -> None:
    """No edit lock → instant return."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    try:
        start = time.monotonic()
        wait_for_edit_lock_release(project_file)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1
    finally:
        os.unlink(project_file)


def test_wait_blocks_then_proceeds(tmp_path: Path) -> None:
    """Lock held by subprocess, released after delay → blocks then returns."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    lock_file = f"{project_file}.edit_lock"

    # Start a subprocess that holds the lock briefly
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    try:
        # Write the subprocess PID as the edit lock holder
        with open(lock_file, "w") as lf:
            lf.write(str(proc.pid))

        # Release the lock from a thread after a short delay
        def release_after_delay() -> None:
            time.sleep(0.3)  # sase-test-wait: edit-lock delay is asserted
            proc.terminate()
            proc.wait()
            try:
                os.unlink(lock_file)
            except FileNotFoundError:
                pass

        t = threading.Thread(target=release_after_delay)
        t.start()

        start = time.monotonic()
        wait_for_edit_lock_release(project_file, poll_interval=0.1)
        elapsed = time.monotonic() - start

        assert elapsed >= 0.2  # waited for the lock
        t.join()
    finally:
        proc.terminate()
        proc.wait()
        os.unlink(project_file)
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


def test_wait_same_process_skips(tmp_path: Path) -> None:
    """Lock with current PID → instant return (same-process exemption)."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        start = time.monotonic()
        wait_for_edit_lock_release(project_file)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_wait_timeout_raises(tmp_path: Path) -> None:
    """Lock with alive PID + short timeout → LockTimeoutError."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    lock_file = f"{project_file}.edit_lock"

    # Start a subprocess to hold a live PID
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    try:
        with open(lock_file, "w") as lf:
            lf.write(str(proc.pid))

        with pytest.raises(LockTimeoutError):
            wait_for_edit_lock_release(project_file, poll_interval=0.05, timeout=0.2)
    finally:
        proc.terminate()
        proc.wait()
        os.unlink(project_file)
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


def test_patch_lock_waits_for_edit_lock(tmp_path: Path) -> None:
    """Integration: edit lock held → patch_lock blocks until released."""
    with tempfile.NamedTemporaryFile(dir=tmp_path, suffix=".sase", delete=False) as f:
        project_file = f.name
    lock_file = f"{project_file}.edit_lock"

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    try:
        with open(lock_file, "w") as lf:
            lf.write(str(proc.pid))

        acquired = threading.Event()

        def acquire_in_thread() -> None:
            with legacy_changespec_lock(project_file):
                acquired.set()

        t = threading.Thread(target=acquire_in_thread)
        t.start()

        # Lock should NOT be acquired yet
        assert not acquired.wait(timeout=0.3)

        # Release the edit lock
        proc.terminate()
        proc.wait()
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass

        # Now the patch lock should proceed
        assert acquired.wait(timeout=2.0)
        t.join(timeout=2.0)
    finally:
        proc.terminate()
        proc.wait()
        os.unlink(project_file)
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass
        try:
            os.unlink(f"{project_file}.lock")
        except FileNotFoundError:
            pass

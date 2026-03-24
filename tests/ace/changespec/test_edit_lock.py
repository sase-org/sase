"""Tests for edit lock functions."""

import os
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from sase.ace.changespec.locking import (
    LockTimeoutError,
    acquire_edit_lock,
    changespec_lock,
    is_edit_locked,
    release_edit_lock,
    wait_for_edit_lock_release,
)


def test_acquire_creates_lock_file() -> None:
    """Verify .edit_lock is created with current PID."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        lock_file = f"{project_file}.edit_lock"
        assert os.path.exists(lock_file)
        with open(lock_file) as lf:
            assert lf.read().strip() == str(os.getpid())
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_release_removes_lock_file() -> None:
    """Verify release removes the .edit_lock file."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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


def test_is_edit_locked_returns_true_for_active_lock() -> None:
    """Active lock (current PID) returns True."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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


def test_is_edit_locked_cleans_stale_lock() -> None:
    """Dead PID lock is removed and returns False."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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


def test_is_edit_locked_returns_false_when_no_lock() -> None:
    """No lock file returns False."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        assert is_edit_locked(project_file) is False
    finally:
        os.unlink(project_file)


def test_release_nonexistent_lock_is_noop() -> None:
    """Releasing a lock that doesn't exist doesn't raise."""
    release_edit_lock("/tmp/nonexistent_project_file.gp")


# --- wait_for_edit_lock_release tests ---


def test_wait_returns_immediately_when_unlocked() -> None:
    """No edit lock → instant return."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        start = time.monotonic()
        wait_for_edit_lock_release(project_file)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1
    finally:
        os.unlink(project_file)


def test_wait_blocks_then_proceeds() -> None:
    """Lock held by subprocess, released after delay → blocks then returns."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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
            time.sleep(0.3)
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


def test_wait_same_process_skips() -> None:
    """Lock with current PID → instant return (same-process exemption)."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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


def test_wait_timeout_raises() -> None:
    """Lock with alive PID + short timeout → LockTimeoutError."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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


def test_changespec_lock_waits_for_edit_lock() -> None:
    """Integration: edit lock held → changespec_lock blocks until released."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
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
            with changespec_lock(project_file):
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

        # Now the changespec_lock should proceed
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

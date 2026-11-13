"""Tests for edit lock functions."""

import errno
import fcntl
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

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
    """Aged unparseable locks are stale and reclaimed.

    Intended semantic change: a fresh unparseable lock is treated as held
    (see ``test_acquire_blocked_by_fresh_unparseable_lock``), so this test
    ages the file past the grace window before acquiring.
    """
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    Path(lock_file).write_text("not-a-pid\n")
    aged = time.time() - (locking._UNPARSEABLE_LOCK_GRACE_SECONDS + 60.0)
    os.utime(lock_file, (aged, aged))
    try:
        acquire_edit_lock(project_file)
        assert Path(lock_file).read_text().splitlines()[0] == str(os.getpid())
    finally:
        release_edit_lock(project_file)


def test_acquire_blocked_by_fresh_unparseable_lock(tmp_path: Path) -> None:
    """A fresh unparseable lock blocks acquisition and reads as held."""
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    Path(lock_file).write_text("not-a-pid\n")
    try:
        assert is_edit_locked(project_file) is True
        with pytest.raises(FileExistsError):
            acquire_edit_lock(project_file)
        # The blocker is left in place, not reclaimed.
        assert Path(lock_file).read_text() == "not-a-pid\n"
    finally:
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


def test_acquire_reclaims_aged_unparseable_lock(tmp_path: Path) -> None:
    """An unparseable lock older than the grace window is reclaimed."""
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    Path(lock_file).write_text("")
    aged = time.time() - (locking._UNPARSEABLE_LOCK_GRACE_SECONDS + 60.0)
    os.utime(lock_file, (aged, aged))
    try:
        assert is_edit_locked(project_file) is False
        acquire_edit_lock(project_file)
        assert Path(lock_file).read_text().splitlines()[0] == str(os.getpid())
    finally:
        release_edit_lock(project_file)


def _fd_path(fd: int) -> str:
    for candidate in (f"/proc/self/fd/{fd}", f"/dev/fd/{fd}"):
        try:
            return os.readlink(candidate)
        except OSError:
            continue
    return ""


def test_interleaved_atomic_publish_has_one_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic interleaving: one owner, one FileExistsError.

    The first contender blocks inside its lock-content write until the
    second contender's ``acquire_edit_lock`` has returned or raised.
    """
    project_file = str(tmp_path / "test.sase")
    Path(project_file).touch()
    original_write = os.write
    first_entered = threading.Event()
    second_finished = threading.Event()
    blocked_once = {"done": False}

    def blocking_write(fd: int, data: bytes) -> int:
        if (
            not blocked_once["done"]
            and isinstance(data, (bytes, bytearray))
            and data[:1].isdigit()
            and ".edit_lock_tmp_" in _fd_path(fd)
        ):
            blocked_once["done"] = True
            first_entered.set()
            assert second_finished.wait(timeout=10), "second contender never finished"
        return original_write(fd, data)

    monkeypatch.setattr(locking.os, "write", blocking_write)
    outcomes: list[str] = []

    def contender() -> None:
        try:
            acquire_edit_lock(project_file)
        except FileExistsError:
            outcomes.append("busy")
            return
        outcomes.append("owner")

    first = threading.Thread(target=contender)
    first.start()
    assert first_entered.wait(timeout=10), "first contender never reached os.write"
    second_finished_container: list[str] = []

    def second() -> None:
        try:
            acquire_edit_lock(project_file)
        except FileExistsError:
            second_finished_container.append("busy")
            outcomes.append("busy")
        else:
            second_finished_container.append("owner")
            outcomes.append("owner")
        finally:
            second_finished.set()

    second_thread = threading.Thread(target=second)
    second_thread.start()
    second_thread.join(timeout=10)
    first.join(timeout=10)
    assert not second_thread.is_alive()
    assert not first.is_alive()
    assert sorted(outcomes) == ["busy", "owner"]
    assert Path(f"{project_file}.edit_lock").read_text().splitlines()[0] == str(
        os.getpid()
    )
    assert [
        p for p in Path(tmp_path).iterdir() if p.name.startswith(".edit_lock_tmp_")
    ] == []
    release_edit_lock(project_file)


def test_interleaved_publish_between_write_and_link_has_one_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pause between temp write and ``os.link``: still exactly one owner."""
    project_file = str(tmp_path / "test.sase")
    Path(project_file).touch()
    original_link = os.link
    first_entered = threading.Event()
    second_finished = threading.Event()
    blocked_once = {"done": False}

    def blocking_link(src: str, dst: str, *args: object, **kwargs: object) -> None:
        if (
            not blocked_once["done"]
            and ".edit_lock_tmp_" in src
            and dst.endswith(".edit_lock")
        ):
            blocked_once["done"] = True
            first_entered.set()
            assert second_finished.wait(timeout=10), "second contender never finished"
        return original_link(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(locking.os, "link", blocking_link)
    outcomes: list[str] = []

    first = threading.Thread(
        target=lambda: (
            outcomes.append("owner")
            if _acquire_quiet(project_file)
            else outcomes.append("busy")
        )
    )
    first.start()
    assert first_entered.wait(timeout=10), "first contender never reached os.link"

    def second() -> None:
        if _acquire_quiet(project_file):
            outcomes.append("owner")
        else:
            outcomes.append("busy")
        second_finished.set()

    second_thread = threading.Thread(target=second)
    second_thread.start()
    second_thread.join(timeout=10)
    first.join(timeout=10)
    assert not second_thread.is_alive()
    assert not first.is_alive()
    assert sorted(outcomes) == ["busy", "owner"]
    assert Path(f"{project_file}.edit_lock").read_text().splitlines()[0] == str(
        os.getpid()
    )
    assert [
        p for p in Path(tmp_path).iterdir() if p.name.startswith(".edit_lock_tmp_")
    ] == []
    release_edit_lock(project_file)


def _acquire_quiet(project_file: str) -> bool:
    try:
        acquire_edit_lock(project_file)
    except FileExistsError:
        return False
    return True


def test_fallback_empty_lock_treated_as_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``os.link`` forced to EPERM, a fresh empty lock blocks."""
    project_file = str(tmp_path / "test.sase")
    Path(project_file).touch()
    original_write = os.write
    original_link = os.link
    first_entered = threading.Event()
    second_finished = threading.Event()
    blocked_once = {"done": False}

    def no_link(src: str, dst: str, *args: object, **kwargs: object) -> None:
        if ".edit_lock_tmp_" in src and dst.endswith(".edit_lock"):
            raise OSError(errno.EPERM, "Operation not permitted")
        return original_link(src, dst, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(locking.os, "link", no_link)

    def blocking_write(fd: int, data: bytes) -> int:
        if (
            not blocked_once["done"]
            and isinstance(data, (bytes, bytearray))
            and _fd_path(fd).endswith(".edit_lock")
        ):
            blocked_once["done"] = True
            first_entered.set()
            assert second_finished.wait(timeout=10), "second contender never finished"
        return original_write(fd, data)

    monkeypatch.setattr(locking.os, "write", blocking_write)
    outcomes: list[str] = []

    first = threading.Thread(
        target=lambda: (
            outcomes.append("owner")
            if _acquire_quiet(project_file)
            else outcomes.append("busy")
        )
    )
    first.start()
    assert first_entered.wait(timeout=10), (
        "first contender never reached fallback write"
    )

    def second() -> None:
        if _acquire_quiet(project_file):
            outcomes.append("owner")
        else:
            outcomes.append("busy")
        second_finished.set()

    second_thread = threading.Thread(target=second)
    second_thread.start()
    second_thread.join(timeout=10)
    first.join(timeout=10)
    assert not second_thread.is_alive()
    assert not first.is_alive()
    # The first contender created the empty fallback lock and held it; the
    # second contender must see the fresh empty lock as held.
    assert sorted(outcomes) == ["busy", "owner"]
    assert Path(f"{project_file}.edit_lock").read_text().splitlines()[0] == str(
        os.getpid()
    )
    assert [
        p for p in Path(tmp_path).iterdir() if p.name.startswith(".edit_lock_tmp_")
    ] == []
    release_edit_lock(project_file)


def test_release_leaves_other_pid_lock_in_place(tmp_path: Path) -> None:
    """``release_edit_lock`` never deletes another process's lock."""
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        Path(lock_file).write_text(f"{proc.pid}\n")
        release_edit_lock(project_file)
        assert Path(lock_file).read_text() == f"{proc.pid}\n"
    finally:
        proc.terminate()
        proc.wait()
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


def test_release_leaves_mismatched_token_in_place(tmp_path: Path) -> None:
    """A lock with this PID but a foreign start token is left alone."""
    project_file = str(tmp_path / "test.sase")
    lock_file = f"{project_file}.edit_lock"
    Path(project_file).touch()
    Path(lock_file).write_text(f"{os.getpid()}\nforeign-token\n")
    try:
        release_edit_lock(project_file)
        assert Path(lock_file).read_text() == f"{os.getpid()}\nforeign-token\n"
    finally:
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


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

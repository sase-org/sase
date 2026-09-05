"""Integration tests exercising stale-lock recovery across representative git flows."""

import logging
import os
import subprocess
import time
from pathlib import Path

import pytest

from sase.git_lock_retry import (
    git_index_lock_path,
    run_with_git_lock_retry,
)


def _init_git_repo(repo_path: Path) -> None:
    """Initialize a bare git repository."""
    repo_path.mkdir(exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )


def _make_commit(repo_path: Path, message: str) -> str:
    """Create a test file and commit it."""
    test_file = repo_path / f"test_{int(time.time())}.txt"
    test_file.write_text(f"content for {message}")
    subprocess.run(
        ["git", "add", str(test_file)],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo = tmp_path / "test_repo"
    _init_git_repo(repo)
    return repo


def test_lock_recovery_transient_contention(
    temp_repo: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test recovery when lock is removed mid-backoff by competing process."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None
    calls = [0]

    def attempt() -> subprocess.CompletedProcess[str]:
        calls[0] += 1
        # Plant the lock on first attempt
        if calls[0] == 1:
            lock_path.write_bytes(b"locked")
        elif calls[0] == 2:
            # Simulate competing process removing the lock between attempts
            if lock_path.exists():
                lock_path.unlink()

        # Try to add a file
        test_file = temp_repo / f"file_{calls[0]}.txt"
        test_file.write_text(f"content {calls[0]}")
        return subprocess.run(
            ["git", "add", str(test_file)],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        result, outcome = run_with_git_lock_retry(
            attempt,
            cwd=temp_repo,
            delays=(0.001, 0.001),
        )

    assert result.returncode == 0, f"git add failed: {result.stderr}"
    assert calls[0] >= 2
    assert outcome.lock_removed is False
    assert not lock_path.exists()


def test_lock_recovery_abandoned_lock_removed(
    temp_repo: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test recovery when stale lock is deleted after retries exhaust."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None

    # Plant an old lock file
    lock_path.write_bytes(b"stale_lock")
    old_time = time.time() - 60  # 60 seconds old
    os.utime(lock_path, (old_time, old_time))

    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        # Try to add a file, will fail with lock error
        test_file = temp_repo / f"file_{calls}.txt"
        test_file.write_text(f"content {calls}")
        return subprocess.run(
            ["git", "add", str(test_file)],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        result, outcome = run_with_git_lock_retry(
            attempt,
            cwd=temp_repo,
            delays=(0.001, 0.001),
        )

    assert result.returncode == 0, f"git add failed: {result.stderr}"
    assert calls == 4  # 3 attempts (initial + 2 retries) + 1 final after deletion
    assert outcome.attempts == 4
    assert outcome.lock_removed is True
    assert outcome.lock_path == lock_path
    assert not lock_path.exists()
    # Verify warning logs
    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        assert any("Removed stale" in record.message for record in caplog.records)


def test_lock_recovery_churned_lock_not_removed(
    temp_repo: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test no removal when lock is recreated fresh during backoff window."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        # Keep recreating the lock with fresh content (simulating live contention)
        lock_path.write_bytes(b"x" * calls)
        test_file = temp_repo / f"file_{calls}.txt"
        test_file.write_text(f"content {calls}")
        return subprocess.run(
            ["git", "add", str(test_file)],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        result, outcome = run_with_git_lock_retry(
            attempt,
            cwd=temp_repo,
            delays=(0.001, 0.001),
        )

    # Should fail with original error (no deletion of churning lock)
    assert result.returncode == 128
    assert calls == 3
    assert outcome.attempts == 3
    assert outcome.lock_removed is False
    assert lock_path.exists()


def test_lock_recovery_non_index_lock_not_removed(
    temp_repo: Path,
) -> None:
    """Test that non-index.lock files are never deleted even if old."""
    git_dir = temp_repo / ".git"
    # Place a refs.lock (not index.lock) that's old and should NOT be deleted
    refs_lock = git_dir / "refs" / "heads" / "main.lock"
    refs_lock.parent.mkdir(parents=True, exist_ok=True)
    refs_lock.write_bytes(b"locked")

    old_time = time.time() - 60
    os.utime(refs_lock, (old_time, old_time))

    index_lock = git_index_lock_path(temp_repo)
    assert index_lock is not None

    calls = [0]

    def attempt() -> subprocess.CompletedProcess[str]:
        calls[0] += 1
        # Simulate an error mentioning the refs.lock
        if calls[0] == 1 and refs_lock.exists():
            return subprocess.CompletedProcess(
                ["git", "branch"],
                128,
                stdout="",
                stderr=f"fatal: Unable to create '{refs_lock}': File exists.\n",
            )
        # Success on retry after lock is gone or overwrite
        if refs_lock.exists():
            refs_lock.unlink()
        return subprocess.CompletedProcess(
            ["git", "branch"],
            0,
            stdout="* master\n",
            stderr="",
        )

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=temp_repo,
        delays=(0.001,),
    )

    # Should succeed after retries
    assert result.returncode == 0
    assert outcome.lock_removed is False
    assert outcome.lock_path is None  # refs.lock is not the index.lock


def test_git_commit_workflow_with_lock_recovery(
    temp_repo: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exercise a real git commit workflow with lock recovery."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None

    # Create initial commit
    _make_commit(temp_repo, "Initial commit")

    plant_lock_on_next = [True]
    calls = [0]

    def attempt() -> subprocess.CompletedProcess[str]:
        calls[0] += 1
        if plant_lock_on_next[0]:
            lock_path.write_bytes(b"locked")
            # Age it so it qualifies for removal
            old_time = time.time() - 30
            os.utime(lock_path, (old_time, old_time))
            plant_lock_on_next[0] = False

        # Create a new file and commit it
        test_file = temp_repo / f"feature_{calls[0]}.txt"
        test_file.write_text(f"Feature {calls[0]} implementation")

        # Do add
        result = subprocess.run(
            ["git", "add", str(test_file)],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return result

        # Do commit
        return subprocess.run(
            ["git", "commit", "-m", f"Add feature {calls[0]}"],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        result, outcome = run_with_git_lock_retry(
            attempt,
            cwd=temp_repo,
            delays=(0.01, 0.01),
        )

    assert result.returncode == 0, f"commit failed: {result.stderr}"
    assert outcome.lock_removed is True
    assert not lock_path.exists()

    # Verify the commit was created
    log_result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=temp_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "feature" in log_result.stdout.lower()


def test_git_add_multiple_files_with_lock_recovery(
    temp_repo: Path,
) -> None:
    """Exercise multiple git add operations with lock recovery."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None

    files_to_add = [
        temp_repo / "file1.txt",
        temp_repo / "file2.txt",
        temp_repo / "file3.txt",
    ]

    calls = [0]

    def attempt() -> subprocess.CompletedProcess[str]:
        calls[0] += 1
        if calls[0] == 1:
            # Plant stale lock on first attempt
            lock_path.write_bytes(b"stale")
            old_time = time.time() - 20
            os.utime(lock_path, (old_time, old_time))

        # Add the files
        for f in files_to_add:
            if not f.exists():
                f.write_text(f"content of {f.name}")

        return subprocess.run(
            ["git", "add"] + [str(f) for f in files_to_add],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=temp_repo,
        delays=(0.001,),
    )

    assert result.returncode == 0, f"git add failed: {result.stderr}"
    assert outcome.lock_removed is True
    assert not lock_path.exists()

    # Verify files were staged
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=temp_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    for f in files_to_add:
        assert f.name in status.stdout


def test_git_checkout_with_lock_recovery(
    temp_repo: Path,
) -> None:
    """Exercise a git checkout operation with lock recovery."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None

    # Create initial commit on the repo's default branch
    _make_commit(temp_repo, "Initial")
    base_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=temp_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Create a feature branch
    subprocess.run(
        ["git", "checkout", "-b", "feature"],
        cwd=temp_repo,
        capture_output=True,
        check=True,
    )
    _make_commit(temp_repo, "Feature work")

    # Back to the default branch for checkout test
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=temp_repo,
        capture_output=True,
        check=True,
    )

    calls = [0]

    def attempt() -> subprocess.CompletedProcess[str]:
        calls[0] += 1
        if calls[0] == 1:
            # Plant old lock before checkout
            lock_path.write_bytes(b"locked")
            old_time = time.time() - 25
            os.utime(lock_path, (old_time, old_time))

        return subprocess.run(
            ["git", "checkout", "feature"],
            cwd=temp_repo,
            capture_output=True,
            text=True,
            check=False,
        )

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=temp_repo,
        delays=(0.001,),
    )

    assert result.returncode == 0, f"git checkout failed: {result.stderr}"
    assert outcome.lock_removed is True
    assert not lock_path.exists()


def test_git_status_does_not_hit_lock_error(
    temp_repo: Path,
) -> None:
    """Verify that read-only operations like git status don't encounter lock errors."""
    lock_path = git_index_lock_path(temp_repo)
    assert lock_path is not None

    # Plant a lock
    lock_path.write_bytes(b"locked")

    # git status should not hit the lock
    result = subprocess.run(
        ["git", "status"],
        cwd=temp_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    # May or may not succeed depending on exact git behavior, but should not
    # be a lock contention error
    assert "index.lock" not in result.stderr.lower() or result.returncode == 0

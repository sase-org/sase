"""Tests for the shared git lock retry and recovery policy."""

import logging
import os
from pathlib import Path
import subprocess
import time

import pytest

from sase.git_lock_retry import (
    DEFAULT_GIT_LOCK_RETRY_DELAYS,
    ENV_GIT_LOCK_RETRY_DELAYS,
    git_index_lock_path,
    git_lock_retry_delays,
    _is_retryable_git_lock_error,
    run_with_git_lock_retry,
)


def _make_repo_and_lock(tmp_path: Path) -> Path:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock_path = git_dir / "index.lock"
    lock_path.write_bytes(b"locked")
    return lock_path


def _lock_error(lock_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["git", "add", "."],
        128,
        stdout="",
        stderr=f"fatal: Unable to create '{lock_path}': File exists.\n",
    )


def _success() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["git", "add", "."],
        0,
        stdout="ok",
        stderr="",
    )


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (128, "fatal: Unable to create '/repo/.git/index.lock'", True),
        (128, b"fatal: unable to create refs/heads/main.lock", True),
        (128, "fatal: index.lock already exists", True),
        (1, "fatal: Unable to create '/repo/.git/index.lock'", True),
        (1, "fatal: index.lock was mentioned only as context", False),
        (128, "fatal: another git process seems to be running", False),
        (0, None, False),
    ],
)
def test_is_retryable_git_lock_error_truth_table(
    returncode: int,
    output: str | bytes | None,
    expected: bool,
) -> None:
    assert _is_retryable_git_lock_error(returncode, output) is expected


def test_git_lock_retry_delays_defaults_and_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_GIT_LOCK_RETRY_DELAYS, raising=False)
    assert git_lock_retry_delays() == DEFAULT_GIT_LOCK_RETRY_DELAYS

    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0, 0.025,1.5")
    assert git_lock_retry_delays() == (0.0, 0.025, 1.5)


@pytest.mark.parametrize("raw", ["", "wat", "0.1,,0.2", "-0.1,0.2"])
def test_git_lock_retry_delays_invalid_env_uses_default(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, raw)
    assert git_lock_retry_delays() == DEFAULT_GIT_LOCK_RETRY_DELAYS


def test_run_with_git_lock_retry_succeeds_mid_schedule(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls < 3:
            return _lock_error(lock_path)
        lock_path.unlink()
        return _success()

    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        result, outcome = run_with_git_lock_retry(
            attempt,
            cwd=tmp_path,
            delays=(0.001, 0.001, 0.001),
        )

    assert result.returncode == 0
    assert calls == 3
    assert outcome.attempts == 3
    assert outcome.attempts_made == 3
    assert outcome.lock_removed is False
    assert outcome.lock_path == lock_path
    assert len(caplog.records) == 2
    assert all(str(tmp_path) in record.message for record in caplog.records)
    assert "attempt 2/4" in caplog.records[0].message


def test_run_with_git_lock_retry_removes_lock_persisting_through_window(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _lock_error(lock_path) if lock_path.exists() else _success()

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=tmp_path,
        delays=(0.001, 0.001),
    )

    assert result.returncode == 0
    assert calls == 4
    assert outcome.attempts == 4
    assert outcome.lock_removed is True
    assert outcome.lock_path == lock_path
    assert not lock_path.exists()


def test_run_with_git_lock_retry_does_not_remove_young_churning_lock(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        lock_path.write_bytes(b"x" * calls)
        return _lock_error(lock_path)

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=tmp_path,
        delays=(0.001, 0.001),
    )

    assert result.returncode == 128
    assert calls == 3
    assert outcome.attempts == 3
    assert outcome.lock_removed is False
    assert lock_path.exists()


def test_run_with_git_lock_retry_zero_window_keeps_young_lock(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    failure = _lock_error(lock_path)

    result, outcome = run_with_git_lock_retry(
        lambda: failure,
        cwd=tmp_path,
        delays=(),
    )

    assert result is failure
    assert outcome.attempts == 1
    assert outcome.lock_removed is False
    assert lock_path.exists()


def test_run_with_git_lock_retry_removes_old_lock_without_backoff(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    old = time.time() - 60
    os.utime(lock_path, (old, old))
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _lock_error(lock_path) if lock_path.exists() else _success()

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=tmp_path,
        delays=(),
    )

    assert result.returncode == 0
    assert calls == 2
    assert outcome.attempts == 2
    assert outcome.lock_removed is True
    assert not lock_path.exists()


def test_run_with_git_lock_retry_falls_back_to_canonical_lock_path(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    old = time.time() - 60
    os.utime(lock_path, (old, old))
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if not lock_path.exists():
            return _success()
        return subprocess.CompletedProcess(
            ["git", "add", "."],
            128,
            stdout="",
            stderr="fatal: index.lock already exists",
        )

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=tmp_path,
        delays=(),
    )

    assert result.returncode == 0
    assert calls == 2
    assert outcome.lock_removed is True
    assert outcome.lock_path == lock_path


def test_run_with_git_lock_retry_can_disable_old_lock_removal(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    old = time.time() - 60
    os.utime(lock_path, (old, old))
    failure = _lock_error(lock_path)

    result, outcome = run_with_git_lock_retry(
        lambda: failure,
        cwd=tmp_path,
        delays=(),
        allow_lock_removal=False,
    )

    assert result is failure
    assert outcome.lock_removed is False
    assert lock_path.exists()


def test_run_with_git_lock_retry_never_deletes_for_non_index_lock_error(
    tmp_path: Path,
) -> None:
    index_lock = _make_repo_and_lock(tmp_path)
    old = time.time() - 60
    os.utime(index_lock, (old, old))
    config_lock = tmp_path / ".git" / "config.lock"
    config_lock.write_bytes(b"locked")
    failure = subprocess.CompletedProcess(
        ["git", "config", "test.key", "value"],
        128,
        stdout="",
        stderr=f"fatal: Unable to create '{config_lock}': File exists.\n",
    )
    calls = 0

    def attempt() -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return failure

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=tmp_path,
        delays=(0.001,),
    )

    assert result is failure
    assert calls == 2
    assert outcome.lock_removed is False
    assert outcome.lock_path is None
    assert config_lock.exists()
    assert index_lock.exists()


def test_run_with_git_lock_retry_rejects_index_lock_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_lock = _make_repo_and_lock(repo)
    old = time.time() - 60
    os.utime(repo_lock, (old, old))
    other = tmp_path / "other"
    other.mkdir()
    other_lock = _make_repo_and_lock(other)
    failure = _lock_error(other_lock)

    result, outcome = run_with_git_lock_retry(
        lambda: failure,
        cwd=repo,
        delays=(),
    )

    assert result is failure
    assert outcome.lock_removed is False
    assert outcome.lock_path is None
    assert repo_lock.exists()
    assert other_lock.exists()


def test_run_with_git_lock_retry_deletion_failure_returns_original_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    failure = _lock_error(lock_path)
    original_unlink = Path.unlink

    def fail_lock_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == lock_path:
            raise PermissionError("read-only")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_lock_unlink)
    with caplog.at_level(logging.WARNING, logger="sase.git_lock_retry"):
        result, outcome = run_with_git_lock_retry(
            lambda: failure,
            cwd=tmp_path,
            delays=(0.001,),
        )

    assert result is failure
    assert outcome.attempts == 2
    assert outcome.lock_removed is False
    assert lock_path.exists()
    assert "Failed to remove stale git index lock" in caplog.records[-1].message


def test_run_with_git_lock_retry_supports_custom_native_result_adapter(
    tmp_path: Path,
) -> None:
    lock_path = _make_repo_and_lock(tmp_path)
    calls = 0

    def attempt() -> tuple[bool, str | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return False, _lock_error(lock_path).stderr
        lock_path.unlink()
        return True, None

    result, outcome = run_with_git_lock_retry(
        attempt,
        cwd=tmp_path,
        result_adapter=lambda native: (0 if native[0] else 128, native[1]),
        delays=(0.001,),
    )

    assert result == (True, None)
    assert outcome.attempts == 2
    assert outcome.lock_removed is False


def test_git_index_lock_path_resolves_git_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    completed = subprocess.CompletedProcess(
        ["git", "rev-parse", "--git-dir"],
        0,
        stdout="../metadata/worktrees/repo\n",
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    assert (
        git_index_lock_path(tmp_path)
        == (tmp_path / "../metadata/worktrees/repo/index.lock").resolve()
    )

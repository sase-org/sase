"""Tests for shared SDD store git-write serialization."""

import fcntl
from pathlib import Path
import subprocess
import time

import pytest

from sase.sdd._git_contention import (
    DEFAULT_GIT_LOCK_RETRY_DELAYS,
    ENV_GIT_LOCK_RETRY_DELAYS,
    STORE_WRITE_LOCK_FILENAME,
    _git_lock_retry_delays,
    store_git_write_lock,
)


def test_store_git_write_lock_has_bounded_fail_open_timeout(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    lock_path = tmp_path / ".git" / STORE_WRITE_LOCK_FILENAME

    with lock_path.open("a+", encoding="utf-8") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()

        with store_git_write_lock(tmp_path, timeout=0.03) as acquired:
            elapsed = time.monotonic() - started
            assert acquired is False

        assert elapsed >= 0.02
        assert elapsed < 1.0
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)

    with store_git_write_lock(tmp_path, timeout=0) as acquired:
        assert acquired is True


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_sdd_git_lock_retry_non_finite_env_uses_default(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, raw)

    assert _git_lock_retry_delays() == DEFAULT_GIT_LOCK_RETRY_DELAYS

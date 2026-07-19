"""Tests for shared SDD store git-write serialization."""

import fcntl
from pathlib import Path
import subprocess
import time

import pytest

from sase.git_lock_retry import (
    DEFAULT_GIT_LOCK_RETRY_DELAYS,
    ENV_GIT_LOCK_RETRY_DELAYS as ENV_SHARED_GIT_LOCK_RETRY_DELAYS,
)
from sase.sdd._git_contention import (
    ENV_GIT_LOCK_RETRY_DELAYS as ENV_SDD_GIT_LOCK_RETRY_DELAYS,
    STORE_WRITE_LOCK_FILENAME,
    _git_lock_retry_delays,
    store_git_write_lock,
)


def test_sdd_retry_delays_use_global_default_with_legacy_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_SHARED_GIT_LOCK_RETRY_DELAYS, raising=False)
    monkeypatch.delenv(ENV_SDD_GIT_LOCK_RETRY_DELAYS, raising=False)
    assert _git_lock_retry_delays() == DEFAULT_GIT_LOCK_RETRY_DELAYS

    monkeypatch.setenv(ENV_SHARED_GIT_LOCK_RETRY_DELAYS, "0.001, 0.002")
    assert _git_lock_retry_delays() == (0.001, 0.002)

    monkeypatch.setenv(ENV_SDD_GIT_LOCK_RETRY_DELAYS, "0.003, 0.004")
    assert _git_lock_retry_delays() == (0.003, 0.004)


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

"""Tests for shared SDD store git-write serialization."""

import fcntl
import multiprocessing
from pathlib import Path
import subprocess
import time
from typing import Any

import pytest

from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock
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


def _acquire_epic_plan_launch_lock(repo_root: str, acquired: Any) -> None:
    with epic_plan_launch_lock(Path(repo_root)):
        acquired.set()


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


def test_epic_plan_launch_lock_blocks_other_process_for_same_canonical_store(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    alias = tmp_path / "repo-alias"
    alias.symlink_to(repo, target_is_directory=True)
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    process = context.Process(
        target=_acquire_epic_plan_launch_lock,
        args=(str(alias), acquired),
    )

    with epic_plan_launch_lock(repo):
        process.start()
        assert acquired.wait(0.1) is False

    assert acquired.wait(2.0) is True
    process.join(timeout=2.0)
    assert process.exitcode == 0


def test_epic_plan_launch_lock_does_not_serialize_distinct_stores(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    process = context.Process(
        target=_acquire_epic_plan_launch_lock,
        args=(str(second), acquired),
    )

    with epic_plan_launch_lock(first):
        process.start()
        assert acquired.wait(2.0) is True

    process.join(timeout=2.0)
    assert process.exitcode == 0


def test_epic_plan_launch_lock_releases_after_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="launch failed"):
        with epic_plan_launch_lock(tmp_path):
            raise RuntimeError("launch failed")

    with epic_plan_launch_lock(tmp_path):
        pass

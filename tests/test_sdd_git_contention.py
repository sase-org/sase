"""Tests for shared SDD store git-write serialization."""

import fcntl
import multiprocessing
import os
from pathlib import Path
import subprocess
import time
from typing import Any

import pytest

from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock
from sase.bead.cli_work_from_plan_store import (
    DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS,
    ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT,
    _epic_plan_launch_lock_timeout,
)
from sase.bead.cli_work_from_plan_types import PlanFileWorkError
from sase.git_lock_retry import (
    DEFAULT_GIT_LOCK_RETRY_DELAYS,
    ENV_GIT_LOCK_RETRY_DELAYS as ENV_SHARED_GIT_LOCK_RETRY_DELAYS,
)
from sase.sdd._git_contention import (
    DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS,
    DEFAULT_STORE_WRITE_LOCK_SLOW_WAIT_SECONDS,
    DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS,
    ENV_GIT_LOCK_RETRY_DELAYS as ENV_SDD_GIT_LOCK_RETRY_DELAYS,
    ENV_STORE_WRITE_LOCK_TIMEOUT,
    STORE_WRITE_LOCK_FILENAME,
    _store_write_lock_timeout,
    _StoreWriteLockUsageError,
    _git_lock_retry_delays,
    handoff_store_git_write_lock,
    store_git_write_lock,
    store_git_write_lock_factory,
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


def test_worktree_mutating_callers_wait_far_longer_than_single_command_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_STORE_WRITE_LOCK_TIMEOUT, raising=False)

    assert (
        _store_write_lock_timeout(DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS)
        == DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS
    )
    assert (
        _store_write_lock_timeout(DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS)
        == DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS
    )
    assert (
        DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS
        > DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS * 10
    )

    # One knob still overrides every call site, including the longer bound.
    monkeypatch.setenv(ENV_STORE_WRITE_LOCK_TIMEOUT, "2.5")
    assert _store_write_lock_timeout(DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS) == 2.5
    assert (
        _store_write_lock_timeout(DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS) == 2.5
    )

    monkeypatch.setenv(ENV_STORE_WRITE_LOCK_TIMEOUT, "not-a-number")
    assert (
        _store_write_lock_timeout(DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS)
        == DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS
    )


def test_worktree_mutation_wait_is_used_and_env_configurable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    lock_path = tmp_path / ".git" / STORE_WRITE_LOCK_FILENAME
    monkeypatch.setenv(ENV_STORE_WRITE_LOCK_TIMEOUT, "0.05")
    waits: list[float] = []
    monkeypatch.setattr(
        "sase.sdd._git_contention._acquire_store_write_lock",
        lambda fd, *, timeout: waits.append(timeout) or False,
    )

    with store_git_write_lock(tmp_path, op="bead.claim", mutates_worktree=True) as ok:
        assert ok is False
    with store_git_write_lock(tmp_path, op="sdd.recovery.notice") as ok:
        assert ok is False

    assert waits == [0.05, 0.05]
    assert lock_path.exists()

    monkeypatch.delenv(ENV_STORE_WRITE_LOCK_TIMEOUT)
    waits.clear()
    with store_git_write_lock(tmp_path, op="bead.claim", mutates_worktree=True):
        pass
    with store_git_write_lock(tmp_path, op="sdd.recovery.notice"):
        pass

    assert waits == [
        DEFAULT_WORKTREE_MUTATION_LOCK_TIMEOUT_SECONDS,
        DEFAULT_STORE_WRITE_LOCK_TIMEOUT_SECONDS,
    ]


def test_fail_open_warning_names_the_operation_that_proceeded_unlocked(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    lock_path = tmp_path / ".git" / STORE_WRITE_LOCK_FILENAME
    lock_factory = store_git_write_lock_factory(op="bead.claim", mutates_worktree=True)

    with lock_path.open("a+", encoding="utf-8") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        with caplog.at_level("WARNING", logger="sase.sdd._git_contention"):
            with lock_factory(tmp_path, timeout=0.01) as acquired:  # type: ignore[call-arg]
                assert acquired is False
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)

    assert "bead.claim" in caplog.text
    assert str(lock_path) in caplog.text


def test_store_git_write_lock_records_durable_wait_with_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    records: list[dict[str, Any]] = []
    monkeypatch.setattr("sase.logs.log_tui_launch_timing", records.append)

    with store_git_write_lock(tmp_path, op="bead.plan_link") as acquired:
        assert acquired is True

    record = records[-1]
    assert record["operation"] == "store_git_write_lock"
    assert record["op"] == "bead.plan_link"
    assert record["repo_root"] == str(tmp_path.resolve())
    assert record["acquired"] is True
    assert record["failed_open"] is False
    assert record["outcome"] == "acquired"
    assert record["waited_ms"] >= 0
    assert record["stages"][0]["stage"] == "store_write_lock_wait"


def test_store_git_write_lock_warns_after_slow_successful_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setattr(
        "sase.sdd._git_contention.DEFAULT_STORE_WRITE_LOCK_SLOW_WAIT_SECONDS",
        0.0,
    )

    with caplog.at_level("WARNING", logger="sase.sdd._git_contention"):
        with store_git_write_lock(tmp_path, op="bead.plan_link") as acquired:
            assert acquired is True

    assert "Slow SDD store write lock acquisition" in caplog.text
    assert "bead.plan_link" in caplog.text
    assert DEFAULT_STORE_WRITE_LOCK_SLOW_WAIT_SECONDS > 0


def test_store_git_write_lock_requires_explicit_handoff_for_nested_use(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    with store_git_write_lock(tmp_path) as acquired:
        assert acquired is True
        with handoff_store_git_write_lock(tmp_path) as handed_off:
            assert handed_off is True
        with pytest.raises(_StoreWriteLockUsageError, match="already held"):
            with store_git_write_lock(tmp_path):
                pass

    with pytest.raises(_StoreWriteLockUsageError, match="does not hold"):
        with handoff_store_git_write_lock(tmp_path):
            pass


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


def test_epic_plan_launch_lock_timeout_env_is_positive_and_finite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT, raising=False)
    assert (
        _epic_plan_launch_lock_timeout()
        == DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS
    )

    monkeypatch.setenv(ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT, "0.125")
    assert _epic_plan_launch_lock_timeout() == 0.125

    for rejected in ("0", "-1", "nan", "inf", "not-a-number"):
        monkeypatch.setenv(ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT, rejected)
        assert (
            _epic_plan_launch_lock_timeout()
            == DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS
        )


def test_epic_plan_launch_lock_expiry_names_holder_and_resume_command(
    tmp_path: Path,
) -> None:
    holder_plan = tmp_path / "holder plan.md"
    waiting_plan = tmp_path / "waiting plan.md"

    with epic_plan_launch_lock(tmp_path, plan_file=holder_plan):
        with pytest.raises(PlanFileWorkError) as excinfo:
            with epic_plan_launch_lock(
                tmp_path,
                plan_file=waiting_plan,
                timeout=0.02,
            ):
                pass

    message = str(excinfo.value)
    assert f"holder pid {os.getpid()}" in message
    assert str(holder_plan) in message
    assert "Resume with" in message
    assert excinfo.value.resume_command == (f"sase bead work '{waiting_plan}'")

    # Expiry does not disturb the holder, and release clears stale identity.
    with epic_plan_launch_lock(tmp_path, plan_file=waiting_plan, timeout=0.02):
        pass

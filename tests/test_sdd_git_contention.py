"""Tests for shared SDD store git-write serialization."""

import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import time
from contextvars import Context
from typing import Any

import pytest

from sase.bead.cli_location import resolve_workspace_anchor
from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.cli_work_from_plan_store import (
    DEFAULT_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT_SECONDS,
    DEFAULT_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT_SECONDS,
    ENV_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT,
    ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT,
    _epic_approval_preflight_lock_timeout,
    _epic_plan_launch_lock_path,
    _epic_plan_launch_lock_timeout,
    epic_launch_lock_anchor,
    epic_plan_launch_lock,
    require_epic_launch_store_health,
)
from sase.bead.cli_work_from_plan_types import PlanFileWorkError
from sase.core.paths import sase_projects_dir
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
from sase.sdd._store_types import SddMaterializationError
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _acquire_epic_plan_launch_lock(anchor: str, acquired: Any) -> None:
    def acquire() -> None:
        with epic_plan_launch_lock(Path(anchor)) as locked:
            assert locked is True
            acquired.set()

    Context().run(acquire)


def _hold_epic_plan_launch_lock(
    anchor: str,
    acquired: Any,
    release: Any,
    plan_file: str,
) -> None:
    with epic_plan_launch_lock(
        Path(anchor),
        plan_file=plan_file,
        op="test holder launch",
    ) as locked:
        assert locked is True
        acquired.set()
        assert release.wait(5.0)


def _register_project(project_name: str, primary: Path) -> None:
    project_dir = sase_projects_dir() / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )


def _write_workspace_marker(
    checkout: Path,
    *,
    project_name: str,
    primary: Path,
) -> None:
    marker_path = checkout / ".sase" / "checkout.json"
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_name,
                "workspace_num": 2,
                "primary_workspace_dir": str(primary),
                "registry_path": str(primary / ".sase" / "registry.json"),
            }
        ),
        encoding="utf-8",
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


def test_epic_launch_lock_anchor_uses_primary_workspace_identity(
    tmp_path: Path,
) -> None:
    first_primary = tmp_path / "workspaces" / "first"
    first_numbered = tmp_path / "managed" / "first_2"
    second_primary = tmp_path / "workspaces" / "second"
    first_primary.mkdir(parents=True)
    first_numbered.mkdir(parents=True)
    second_primary.mkdir(parents=True)
    _register_project("first", first_primary)
    _register_project("second", second_primary)
    _write_workspace_marker(
        first_numbered,
        project_name="first",
        primary=first_primary,
    )

    assert resolve_workspace_anchor(first_primary) == first_primary.resolve()
    assert epic_launch_lock_anchor(first_primary) == epic_launch_lock_anchor(
        first_numbered
    )
    assert epic_launch_lock_anchor(first_primary) != epic_launch_lock_anchor(
        second_primary
    )


def test_epic_plan_launch_lock_blocks_other_process_for_same_canonical_anchor(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    alias = tmp_path / "anchor-alias"
    alias.symlink_to(anchor, target_is_directory=True)
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    process = context.Process(
        target=_acquire_epic_plan_launch_lock,
        args=(str(alias), acquired),
    )

    with epic_plan_launch_lock(anchor) as locked:
        assert locked is True
        process.start()
        assert acquired.wait(0.1) is False

    assert acquired.wait(2.0) is True
    process.join(timeout=2.0)
    assert process.exitcode == 0


def test_epic_plan_launch_lock_does_not_serialize_distinct_anchors(
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

    with epic_plan_launch_lock(first) as locked:
        assert locked is True
        process.start()
        assert acquired.wait(2.0) is True

    process.join(timeout=2.0)
    assert process.exitcode == 0


def test_epic_plan_launch_lock_releases_after_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="launch failed"):
        with epic_plan_launch_lock(tmp_path) as acquired:
            assert acquired is True
            raise RuntimeError("launch failed")

    with epic_plan_launch_lock(tmp_path) as acquired:
        assert acquired is True


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


def test_epic_approval_preflight_lock_timeout_env_is_positive_and_finite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT, raising=False)
    assert (
        _epic_approval_preflight_lock_timeout()
        == DEFAULT_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT_SECONDS
    )

    monkeypatch.setenv(ENV_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT, "0.125")
    assert _epic_approval_preflight_lock_timeout() == 0.125

    for rejected in ("0", "-1", "nan", "inf", "not-a-number"):
        monkeypatch.setenv(ENV_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT, rejected)
        assert (
            _epic_approval_preflight_lock_timeout()
            == DEFAULT_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT_SECONDS
        )


def test_epic_plan_launch_lock_expiry_can_defer_or_raise_with_holder_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    holder_plan = tmp_path / "holder plan.md"
    waiting_plan = tmp_path / "waiting plan.md"
    monkeypatch.setenv(ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT, "0.02")
    context = multiprocessing.get_context("fork")
    holder_acquired = context.Event()
    release_holder = context.Event()
    process = context.Process(
        target=_hold_epic_plan_launch_lock,
        args=(
            str(tmp_path),
            holder_acquired,
            release_holder,
            str(holder_plan),
        ),
    )
    process.start()
    assert holder_acquired.wait(2.0) is True

    try:
        with caplog.at_level(
            "WARNING",
            logger="sase.bead.cli_work_from_plan_store",
        ):
            with epic_plan_launch_lock(
                tmp_path,
                plan_file=waiting_plan,
                op="test deferring waiter",
                raise_on_timeout=False,
            ) as acquired:
                assert acquired is False
        with pytest.raises(PlanFileWorkError) as excinfo:
            with epic_plan_launch_lock(
                tmp_path,
                plan_file=waiting_plan,
            ):
                pass
    finally:
        release_holder.set()
        process.join(timeout=2.0)

    message = str(excinfo.value)
    assert f"holder pid {process.pid}" in message
    assert "test holder launch" in message
    assert str(holder_plan) in message
    assert "Resume with" in message
    assert excinfo.value.resume_command == (f"sase bead work '{waiting_plan}'")
    assert "test deferring waiter" in caplog.text
    assert "test holder launch" in caplog.text
    assert process.exitcode == 0

    # Expiry does not disturb the holder, and release clears stale identity.
    with epic_plan_launch_lock(tmp_path, plan_file=waiting_plan) as acquired:
        assert acquired is True


def test_epic_plan_launch_lock_rejects_reentrant_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_EPIC_PLAN_LAUNCH_LOCK_TIMEOUT, "0.02")

    with epic_plan_launch_lock(tmp_path) as acquired:
        assert acquired is True
        with pytest.raises(RuntimeError, match="already held"):
            with epic_plan_launch_lock(tmp_path):
                pass


def test_epic_launch_preflight_defers_without_materializing_under_contention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = epic_launch_lock_anchor(tmp_path)
    holder_plan = tmp_path / "holder.md"
    monkeypatch.setenv(ENV_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT, "0.02")
    context = multiprocessing.get_context("fork")
    holder_acquired = context.Event()
    release_holder = context.Event()
    process = context.Process(
        target=_hold_epic_plan_launch_lock,
        args=(
            str(anchor),
            holder_acquired,
            release_holder,
            str(holder_plan),
        ),
    )
    process.start()
    assert holder_acquired.wait(2.0) is True
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan_store.resolve_beads_location",
        lambda cwd, *, materialize: calls.append((cwd, materialize)),
    )

    try:
        require_epic_launch_store_health(tmp_path)
    finally:
        release_holder.set()
        process.join(timeout=2.0)

    assert calls == []
    assert process.exitcode == 0


def test_epic_launch_preflight_materializes_and_propagates_failure_when_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, bool]] = []
    expected = SddMaterializationError("sidecar materialization failed")

    def fail_materialization(cwd: Path, *, materialize: bool) -> None:
        calls.append((cwd, materialize))
        raise expected

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan_store.resolve_beads_location",
        fail_materialization,
    )

    with pytest.raises(SddMaterializationError) as excinfo:
        require_epic_launch_store_health(tmp_path)

    assert excinfo.value is expected
    assert calls == [(tmp_path, True)]


def test_plan_file_launch_holds_anchor_lock_before_store_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "approved.md"
    source.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    anchor = epic_launch_lock_anchor()
    lock_path = _epic_plan_launch_lock_path(anchor)

    def assert_locked(*, dry_run: bool) -> None:
        assert dry_run is False
        with lock_path.open("a+", encoding="utf-8") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SddMaterializationError("stop after lock probe")

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        assert_locked,
    )

    with pytest.raises(PlanFileWorkError, match="stop after lock probe"):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    with epic_plan_launch_lock(anchor) as acquired:
        assert acquired is True

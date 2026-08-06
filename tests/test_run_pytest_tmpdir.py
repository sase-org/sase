"""Scratch-directory resolution and reaping in `tools/run_pytest`.

Pytest temporary trees are redirected onto a disk-backed, workspace-scoped
scratch root so the repo checkout stays clean and concurrent workspaces never
share state. These tests pin where that root lands, which overrides are refused
as too broad to clean up, and which stale entries the reaper is allowed to
delete.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from tests._run_pytest_fixtures import load_run_pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def test_configured_pytest_tmpdir_defaults_to_disk_backed_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_TMPDIR_ENV, raising=False)

    scratch_root = runner._configured_pytest_tmpdir()
    workspace_key = hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:8]

    assert scratch_root == Path("/var/tmp") / f"sase-{workspace_key}"
    assert ROOT not in scratch_root.parents


def test_prepare_pytest_tmpdir_honors_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    scratch_root = tmp_path / "pytest scratch"
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(scratch_root))

    assert runner._prepare_pytest_tmpdir() == scratch_root
    assert scratch_root.is_dir()
    assert runner.os.environ["TMPDIR"] == str(scratch_root)
    assert runner.os.environ[runner.PYTEST_TMP_REDIRECTED_ENV] == "1"


def test_configured_pytest_tmpdir_resolves_relative_override_from_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, "build/pytest-scratch")

    assert runner._configured_pytest_tmpdir() == ROOT / "build" / "pytest-scratch"


def test_configured_pytest_tmpdir_rejects_empty_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, "")

    with pytest.raises(pytest.UsageError, match="must not be empty"):
        runner._configured_pytest_tmpdir()


@pytest.mark.parametrize(
    "unsafe_root",
    [Path("/"), Path("/tmp"), Path("/var/tmp"), ROOT, ROOT.parent],
)
def test_configured_pytest_tmpdir_rejects_broad_cleanup_targets(
    monkeypatch: pytest.MonkeyPatch, unsafe_root: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(unsafe_root))

    with pytest.raises(pytest.UsageError, match="dedicated scratch directory"):
        runner._configured_pytest_tmpdir()


def test_reaper_removes_only_stale_pytest_run_directories(tmp_path: Path) -> None:
    runner = load_run_pytest()
    user_root = tmp_path / "pytest-of-user"
    stale_run = user_root / "pytest-1"
    fresh_run = user_root / "pytest-2"
    stale_garbage = user_root / "garbage-deadbeef"
    unrelated = user_root / "other"
    for directory in (stale_run, fresh_run, stale_garbage, unrelated):
        directory.mkdir(parents=True)

    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    stale_lock = stale_run / ".lock"
    stale_lock.touch()
    os.utime(stale_lock, (stale_time, stale_time))
    os.utime(stale_run, (stale_time, stale_time))
    os.utime(stale_garbage, (stale_time, stale_time))
    os.utime(unrelated, (stale_time, stale_time))
    os.utime(fresh_run, (now, now))

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert not stale_run.exists()
    assert not stale_garbage.exists()
    assert fresh_run.is_dir()
    assert unrelated.is_dir()


def test_reaper_removes_stale_top_level_scratch_entries(tmp_path: Path) -> None:
    runner = load_run_pytest()
    stale_inline_snapshot = tmp_path / "inline-snapshot-abc"
    stale_artifact_tree = tmp_path / "tmpab12cd34" / "artifacts"
    fresh_inline_snapshot = tmp_path / "inline-snapshot-def"
    locked_run = tmp_path / "pytest-1"
    skipped_symlink = tmp_path / "inline-snapshot-link"
    for directory in (
        stale_inline_snapshot,
        stale_artifact_tree,
        fresh_inline_snapshot,
        locked_run,
    ):
        directory.mkdir(parents=True)
    lock_path = locked_run / ".lock"
    lock_path.touch()
    skipped_symlink.symlink_to(fresh_inline_snapshot, target_is_directory=True)

    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    os.utime(stale_inline_snapshot, (stale_time, stale_time))
    os.utime(stale_artifact_tree.parent, (stale_time, stale_time))
    os.utime(fresh_inline_snapshot, (now, now))
    os.utime(locked_run, (stale_time, stale_time))
    os.utime(lock_path, (now, now))

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert not stale_inline_snapshot.exists()
    assert not stale_artifact_tree.parent.exists()
    assert fresh_inline_snapshot.is_dir()
    assert locked_run.is_dir()
    assert skipped_symlink.is_symlink()


def test_reaper_preserves_run_with_fresh_lock(tmp_path: Path) -> None:
    runner = load_run_pytest()
    run_directory = tmp_path / "pytest-of-user" / "pytest-1"
    run_directory.mkdir(parents=True)
    lock_path = run_directory / ".lock"
    lock_path.touch()

    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    os.utime(run_directory, (stale_time, stale_time))
    os.utime(lock_path, (now, now))

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert run_directory.is_dir()


def test_reaper_ignores_cleanup_races(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    run_directory = tmp_path / "pytest-of-user" / "pytest-1"
    run_directory.mkdir(parents=True)
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    os.utime(run_directory, (stale_time, stale_time))
    monkeypatch.setattr(
        runner.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(OSError("lost cleanup race")),
    )

    runner._reap_stale_pytest_runs(tmp_path, now=now)

    assert run_directory.is_dir()

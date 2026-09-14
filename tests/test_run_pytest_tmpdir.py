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

from tests._run_pytest_fixtures import (
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)


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
    # isolate_run_pytest_environment already pins TMPDIR/PYTEST_TMP_REDIRECTED_ENV
    # for teardown restoration; what's still needed here is a *distinct*
    # pre-state, since under `just test` the ambient values are already the
    # real scratch root and "1" -- without forcing a placeholder, the
    # assertions below would pass vacuously even if the write never happened.
    monkeypatch.setenv("TMPDIR", "overwritten-by-_prepare_pytest_tmpdir")
    monkeypatch.setenv(runner.PYTEST_TMP_REDIRECTED_ENV, "0")

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


def _age(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp), follow_symlinks=False)


def _workspace_scratch_root(parent: Path, suffix: str) -> Path:
    return parent / f"sase-{suffix}"


def test_sibling_reaper_removes_stale_runs(tmp_path: Path) -> None:
    runner = load_run_pytest()
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    current_root = _workspace_scratch_root(tmp_path, "11111111")
    sibling_root = _workspace_scratch_root(tmp_path, "22222222")
    stale_run = sibling_root / "pytest-of-user" / "pytest-1"
    stale_garbage = sibling_root / "pytest-of-user" / "garbage-deadbeef"
    current_run = current_root / "pytest-of-user" / "pytest-2"
    for directory in (stale_run, stale_garbage, current_run):
        directory.mkdir(parents=True)
    _age(stale_run, stale_time)
    _age(stale_garbage, stale_time)
    _age(current_run, stale_time)

    runner._reap_sibling_pytest_tmpdirs(current_root, tmp_parent=tmp_path, now=now)

    assert not stale_run.exists()
    assert not stale_garbage.exists()
    assert current_run.is_dir()


def test_sibling_reaper_preserves_fresh_and_locked_runs(tmp_path: Path) -> None:
    runner = load_run_pytest()
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    current_root = _workspace_scratch_root(tmp_path, "11111111")
    sibling_root = _workspace_scratch_root(tmp_path, "22222222")
    fresh_run = sibling_root / "pytest-of-user" / "pytest-1"
    locked_run = sibling_root / "pytest-of-user" / "pytest-2"
    for directory in (fresh_run, locked_run):
        directory.mkdir(parents=True)
    fresh_lock = locked_run / ".lock"
    fresh_lock.touch()
    _age(fresh_run, now)
    _age(locked_run, stale_time)
    _age(fresh_lock, now)

    runner._reap_sibling_pytest_tmpdirs(current_root, tmp_parent=tmp_path, now=now)

    assert fresh_run.is_dir()
    assert locked_run.is_dir()


def test_sibling_reaper_preserves_non_matching_names_and_symlinks(
    tmp_path: Path,
) -> None:
    runner = load_run_pytest()
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    current_root = _workspace_scratch_root(tmp_path, "11111111")
    non_matching_root = tmp_path / "sase-nothex"
    real_sibling_root = tmp_path / "real-symlink-target"
    symlink_root = _workspace_scratch_root(tmp_path, "33333333")
    non_matching_run = non_matching_root / "pytest-of-user" / "pytest-1"
    symlink_run = real_sibling_root / "pytest-of-user" / "pytest-2"
    for directory in (non_matching_run, symlink_run):
        directory.mkdir(parents=True)
        _age(directory, stale_time)
    symlink_root.symlink_to(real_sibling_root, target_is_directory=True)

    runner._reap_sibling_pytest_tmpdirs(current_root, tmp_parent=tmp_path, now=now)

    assert non_matching_run.is_dir()
    assert symlink_root.is_symlink()
    assert symlink_run.is_dir()


def test_prepare_pytest_tmpdir_override_disables_sibling_reaping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    current_root = _workspace_scratch_root(tmp_path, "11111111")
    sibling_run = (
        _workspace_scratch_root(tmp_path, "22222222") / "pytest-of-user" / "pytest-1"
    )
    sibling_run.mkdir(parents=True)
    _age(sibling_run, stale_time)
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(current_root))
    reap_stale_pytest_runs = runner._reap_stale_pytest_runs

    def _reap_current_root(
        scratch_root: Path,
        *,
        now: float | None = None,
        horizon_seconds: float = runner.PYTEST_TMP_REAP_HORIZON_SECONDS,
    ) -> None:
        reap_stale_pytest_runs(
            scratch_root,
            now=100_000.0 if now is None else now,
            horizon_seconds=horizon_seconds,
        )

    monkeypatch.setattr(runner, "_reap_stale_pytest_runs", _reap_current_root)

    assert runner._prepare_pytest_tmpdir() == current_root
    assert sibling_run.is_dir()


def test_sibling_reaper_removes_empty_stale_root(tmp_path: Path) -> None:
    runner = load_run_pytest()
    now = 100_000.0
    stale_time = now - runner.PYTEST_TMP_REAP_HORIZON_SECONDS - 1
    current_root = _workspace_scratch_root(tmp_path, "11111111")
    sibling_root = _workspace_scratch_root(tmp_path, "22222222")
    user_root = sibling_root / f"pytest-of-{runner.pwd.getpwuid(os.getuid()).pw_name}"
    user_root.mkdir(parents=True)
    _age(user_root, stale_time)
    _age(sibling_root, stale_time)

    runner._reap_sibling_pytest_tmpdirs(current_root, tmp_parent=tmp_path, now=now)

    assert not sibling_root.exists()


def test_sibling_reaper_keeps_empty_fresh_root(tmp_path: Path) -> None:
    runner = load_run_pytest()
    now = 100_000.0
    sibling_root = _workspace_scratch_root(tmp_path, "22222222")
    sibling_root.mkdir()
    _age(sibling_root, now)

    runner._reap_sibling_pytest_tmpdirs(
        _workspace_scratch_root(tmp_path, "11111111"),
        tmp_parent=tmp_path,
        now=now,
    )

    assert sibling_root.is_dir()

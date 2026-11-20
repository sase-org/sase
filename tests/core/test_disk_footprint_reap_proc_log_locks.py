"""Orphaned proc log-lock sweep tests, driven through the public owner step."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from types import SimpleNamespace

from sase.core.disk_footprint_reap_proc_log_locks import (
    PROC_LOG_LOCK_SWEEP_OWNER,
    proc_log_lock_reap_step,
)


def _patch_step_env(monkeypatch, root: Path, live_ids: set[str]) -> None:
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_proc_log_locks.proc_logs_dir",
        lambda: root,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_proc_log_locks.read_proc_snapshot",
        lambda: SimpleNamespace(
            procs=[SimpleNamespace(proc_id=pid) for pid in live_ids]
        ),
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_proc_log_locks.get_proc_log_lock_orphan_horizon_seconds",
        lambda: 86400.0,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_proc_log_locks.get_proc_log_lock_orphan_max_removals",
        lambda: 2000,
    )


def _write_lock(root: Path, proc_id: str, *, age_seconds: float) -> Path:
    lock = root / f".{proc_id}.log.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - age_seconds
    os.utime(lock, (old, old))
    return lock


def test_orphan_lock_is_reaped_when_old_and_rowless(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    lock = _write_lock(root, "gone-proc", age_seconds=90000)
    _patch_step_env(monkeypatch, root, set())

    step = proc_log_lock_reap_step(apply=True)

    assert not lock.exists()
    assert step.owner == PROC_LOG_LOCK_SWEEP_OWNER
    assert step.mode == "apply"
    assert step.changed is True
    assert "removed 1 orphan proc log lock(s)" in step.summary
    assert step.details["removed"] == 1
    assert step.details["paths"] == [str(lock)]


def test_preview_counts_without_removing(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    lock = _write_lock(root, "gone-proc", age_seconds=90000)
    _patch_step_env(monkeypatch, root, set())

    step = proc_log_lock_reap_step(apply=False)

    assert lock.exists()
    assert step.mode == "dry_run"
    assert "would remove 1 orphan proc log lock(s)" in step.summary
    assert step.details["removed"] == 0
    assert step.details["selected"] == 1


def test_lock_with_live_log_sibling_is_kept(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    (root / "live-proc.log").write_text("x", encoding="utf-8")
    lock = _write_lock(root, "live-proc", age_seconds=90000)
    _patch_step_env(monkeypatch, root, set())

    step = proc_log_lock_reap_step(apply=True)

    assert lock.exists()
    assert step.details["removed"] == 0
    assert step.details["selected"] == 0


def test_lock_with_live_row_is_kept(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    lock = _write_lock(root, "active-proc", age_seconds=90000)
    _patch_step_env(monkeypatch, root, {"active-proc"})

    step = proc_log_lock_reap_step(apply=True)

    assert lock.exists()
    assert step.details["removed"] == 0


def test_fresh_lock_is_kept(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    lock = _write_lock(root, "gone-proc", age_seconds=60)
    _patch_step_env(monkeypatch, root, set())

    step = proc_log_lock_reap_step(apply=True)

    assert lock.exists()
    assert step.details["removed"] == 0


def test_contended_lock_is_skipped(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    lock = _write_lock(root, "gone-proc", age_seconds=90000)
    _patch_step_env(monkeypatch, root, set())
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        step = proc_log_lock_reap_step(apply=True)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert lock.exists()
    assert step.details["removed"] == 0
    assert step.details["selected"] == 1
    assert step.details["skipped"] >= 1


def test_symlinked_lock_is_skipped(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    target = tmp_path / "real.lock"
    target.write_text("", encoding="utf-8")
    link = root / ".gone-proc.log.lock"
    link.symlink_to(target)
    _patch_step_env(monkeypatch, root, set())

    step = proc_log_lock_reap_step(apply=True)

    assert link.is_symlink()
    assert target.exists()
    assert step.details["removed"] == 0


def test_removal_budget_caps_oldest_first(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    now = time.time()
    olds: list[Path] = []
    for index in range(3):
        lock = root / f".proc-{index}.log.lock"
        lock.write_text("", encoding="utf-8")
        old = now - 90000 - index
        os.utime(lock, (old, old))
        olds.append(lock)
    _patch_step_env(monkeypatch, root, set())
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_proc_log_locks.get_proc_log_lock_orphan_max_removals",
        lambda: 2,
    )

    step = proc_log_lock_reap_step(apply=True)

    assert step.details["removed"] == 2
    assert step.details["capped"] is True
    # Oldest first: proc-2 (oldest) and proc-1 go, proc-0 (newest) stays.
    assert not olds[2].exists()
    assert not olds[1].exists()
    assert olds[0].exists()


def test_missing_logs_dir_reports_owner_error(monkeypatch, tmp_path: Path) -> None:
    _patch_step_env(monkeypatch, tmp_path / "nope", set())

    step = proc_log_lock_reap_step(apply=False)

    assert step.mode == "dry_run"
    assert step.owner_error is not None
    assert step.details["errors"] == 1


def test_step_is_blocked_when_proc_store_is_unreadable(monkeypatch) -> None:
    def boom() -> object:
        raise RuntimeError("no Rust here")

    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_proc_log_locks.read_proc_snapshot",
        boom,
    )

    step = proc_log_lock_reap_step(apply=False)

    assert step.owner == PROC_LOG_LOCK_SWEEP_OWNER
    assert step.mode == "blocked"
    assert step.exit_code == 1

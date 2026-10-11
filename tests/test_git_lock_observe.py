"""Tests for Git index-lock host observation adapters."""

from __future__ import annotations

from pathlib import Path

from sase.core.git_lock_wire import GIT_LOCK_FILE_REGULAR, GIT_LOCK_FILE_SYMLINK
from sase.git_lock_observe import (
    canonicalize_lock_path,
    snapshot_lock_path,
)


def test_snapshot_lock_path_refuses_to_follow_symlink_leaf(tmp_path: Path) -> None:
    target = tmp_path / "target.lock"
    target.write_bytes(b"payload")
    lock = tmp_path / "index.lock"
    lock.symlink_to(target)

    snapshot = snapshot_lock_path(lock)

    assert snapshot is not None
    assert snapshot["file_type"] == GIT_LOCK_FILE_SYMLINK
    assert snapshot["path"] == str(canonicalize_lock_path(lock))
    assert snapshot["inode"] == lock.lstat().st_ino
    assert snapshot["size"] == lock.lstat().st_size


def test_snapshot_lock_path_records_regular_file_identity(tmp_path: Path) -> None:
    lock = tmp_path / "index.lock"
    lock.write_bytes(b"locked")
    info = lock.lstat()

    snapshot = snapshot_lock_path(lock)

    assert snapshot is not None
    assert snapshot["file_type"] == GIT_LOCK_FILE_REGULAR
    assert snapshot["inode"] == info.st_ino
    assert snapshot["device"] == info.st_dev
    assert snapshot["size"] == info.st_size
    assert snapshot["mtime_ns"] == info.st_mtime_ns
    assert snapshot["ctime_ns"] == info.st_ctime_ns


def test_snapshot_lock_path_missing_is_none(tmp_path: Path) -> None:
    assert snapshot_lock_path(tmp_path / "index.lock") is None

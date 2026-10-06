"""Tests for bead_push_logs age-plus-count retention in sase.bead._sync_logs."""

from __future__ import annotations

import os
from pathlib import Path

from sase.bead._sync_logs import prune_old_bead_sync_logs

_DAY = 86400.0
_NOW = 1_000_000_000.0


def _write_log(log_dir: Path, name: str, mtime: float) -> Path:
    path = log_dir / name
    path.write_text("log\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _names(log_dir: Path) -> list[str]:
    return sorted(path.name for path in log_dir.glob("sync-*.log") if path.is_file())


def test_old_logs_beyond_keep_count_are_deleted(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for index in range(5):
        _write_log(log_dir, f"sync-old-{index}.log", _NOW - 60 * _DAY)

    deleted = prune_old_bead_sync_logs(
        now=_NOW,
        max_age_days=30.0,
        keep_count=2,
        min_interval_seconds=0,
        log_dir=log_dir,
    )

    assert deleted == 3
    assert _names(log_dir) == ["sync-old-3.log", "sync-old-4.log"]


def test_young_logs_beyond_keep_count_are_kept(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for index in range(5):
        _write_log(log_dir, f"sync-new-{index}.log", _NOW - index)

    deleted = prune_old_bead_sync_logs(
        now=_NOW,
        max_age_days=30.0,
        keep_count=2,
        min_interval_seconds=0,
        log_dir=log_dir,
    )

    assert deleted == 0
    assert len(_names(log_dir)) == 5


def test_zero_max_age_disables_age_predicate(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for index in range(4):
        _write_log(log_dir, f"sync-old-{index}.log", _NOW - 60 * _DAY)

    deleted = prune_old_bead_sync_logs(
        now=_NOW,
        max_age_days=0,
        keep_count=2,
        min_interval_seconds=0,
        log_dir=log_dir,
    )

    assert deleted == 2
    assert _names(log_dir) == ["sync-old-2.log", "sync-old-3.log"]


def test_zero_keep_count_disables_count_predicate(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_log(log_dir, "sync-old.log", _NOW - 60 * _DAY)
    _write_log(log_dir, "sync-new.log", _NOW - 60.0)

    deleted = prune_old_bead_sync_logs(
        now=_NOW,
        max_age_days=30.0,
        keep_count=0,
        min_interval_seconds=0,
        log_dir=log_dir,
    )

    assert deleted == 1
    assert _names(log_dir) == ["sync-new.log"]


def test_second_pass_inside_interval_is_gated(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for index in range(3):
        _write_log(log_dir, f"sync-old-{index}.log", _NOW - 60 * _DAY)

    first = prune_old_bead_sync_logs(
        now=_NOW,
        max_age_days=30.0,
        keep_count=1,
        min_interval_seconds=3600,
        log_dir=log_dir,
    )
    assert first == 2

    _write_log(log_dir, "sync-older.log", _NOW - 90 * _DAY)
    second = prune_old_bead_sync_logs(
        now=_NOW + 60.0,
        max_age_days=30.0,
        keep_count=0,
        min_interval_seconds=3600,
        log_dir=log_dir,
    )
    assert second == 0
    assert "sync-older.log" in _names(log_dir)

    third = prune_old_bead_sync_logs(
        now=_NOW + 3700.0,
        max_age_days=30.0,
        keep_count=0,
        min_interval_seconds=3600,
        log_dir=log_dir,
    )
    assert third == 2
    assert _names(log_dir) == []


def test_retention_marker_is_not_a_sync_log(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write_log(log_dir, "sync-old.log", _NOW - 60 * _DAY)

    prune_old_bead_sync_logs(
        now=_NOW,
        max_age_days=30.0,
        keep_count=0,
        min_interval_seconds=0,
        log_dir=log_dir,
    )

    leftovers = sorted(path.name for path in log_dir.iterdir())
    assert all(not name.startswith("sync-") for name in leftovers)

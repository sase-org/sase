"""Inventory rows for proc log locks, registry tmps, and index backups."""

from __future__ import annotations

import os
import time
from pathlib import Path

from sase.core.disk_footprint_inventory_rows import (
    AGENT_INDEX_BACKUPS_OWNER,
    PROC_LOG_LOCK_SWEEP_OWNER,
    REGISTRY_TMP_SWEEP_OWNER,
    sase_state_rows,
)


def _rows_for(monkeypatch, home: Path) -> list:
    monkeypatch.setenv("SASE_HOME", str(home))
    return list(sase_state_rows(tree_size_fn=lambda path: 0))


def test_procs_logs_row_is_owned_by_lock_sweep(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "procs" / "logs").mkdir(parents=True)

    rows = _rows_for(monkeypatch, home)

    matches = [row for row in rows if row.name == "procs/logs"]
    assert len(matches) == 1
    assert matches[0].owner == PROC_LOG_LOCK_SWEEP_OWNER
    assert matches[0].reclaim == "sase disk reap --apply"


def test_registry_tmp_row_appears_only_for_stale_tmps(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    stale = home / ".agent_name_registry.json.abc123.tmp"
    stale.write_bytes(b"x" * 16)
    old = time.time() - 3600
    os.utime(stale, (old, old))

    rows = _rows_for(monkeypatch, home)

    matches = [row for row in rows if row.owner == REGISTRY_TMP_SWEEP_OWNER]
    assert len(matches) == 1
    assert matches[0].size_bytes == 16
    assert matches[0].reclaim == "sase disk reap --apply"


def test_registry_tmp_row_absent_without_stale_tmps(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    fresh = home / ".agent_name_registry.json.abc123.tmp"
    fresh.write_bytes(b"x" * 16)

    rows = _rows_for(monkeypatch, home)

    assert not [row for row in rows if row.owner == REGISTRY_TMP_SWEEP_OWNER]


def test_index_backup_row_reports_size_and_age_for_humans(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    backup = (
        home / "agent_artifact_index.sqlite.pre-matched-deploy-20260927T064040Z.bak"
    )
    backup.write_bytes(b"x" * 64)
    old = time.time() - 60 * 86400
    os.utime(backup, (old, old))

    rows = _rows_for(monkeypatch, home)

    matches = [row for row in rows if row.owner == AGENT_INDEX_BACKUPS_OWNER]
    assert len(matches) == 1
    assert matches[0].size_bytes == 64
    assert "60d" in matches[0].horizon
    assert "never auto-deleted" in matches[0].horizon
    assert matches[0].reclaim is None


def test_index_backup_row_absent_without_backups(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "agent_artifact_index.sqlite").write_bytes(b"x" * 8)

    rows = _rows_for(monkeypatch, home)

    assert not [row for row in rows if row.owner == AGENT_INDEX_BACKUPS_OWNER]


def test_index_backup_row_counts_journal_kin(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    backup = home / "agent_artifact_index.sqlite.manual.bak"
    backup.write_bytes(b"x" * 32)
    shm = home / "agent_artifact_index.sqlite.manual.bak-shm"
    shm.write_bytes(b"y" * 32)

    rows = _rows_for(monkeypatch, home)

    matches = [row for row in rows if row.owner == AGENT_INDEX_BACKUPS_OWNER]
    assert len(matches) == 1
    assert matches[0].size_bytes == 64

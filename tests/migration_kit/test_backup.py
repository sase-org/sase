"""Tests for the migration kit's backup capture engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat

import pytest

from sase.migration_kit.backup import capture_backup
from sase.migration_kit.paths import CUTOVER_BACKUP_DIR_ENV_VAR


@pytest.fixture(autouse=True)
def _cutover_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cutover"
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(root))
    return root


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "sub").mkdir(parents=True)
    (root / "file.txt").write_text("hello world", encoding="utf-8")
    os.chmod(root / "file.txt", 0o640)
    (root / "link.txt").symlink_to("file.txt")
    dangling = root / "dangling.txt"
    dangling.symlink_to("does-not-exist.txt")
    conn = sqlite3.connect(root / "sub" / "data.sqlite")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    return root


def test_dry_run_reports_without_writing_anything(source_root: Path) -> None:
    outcome = capture_backup(source_root, apply=False)

    assert outcome.ok
    assert outcome.dry_run
    assert outcome.member_count == 5  # file, link, dangling link, sub dir, sqlite
    assert outcome.sqlite_member_count == 1
    assert outcome.symlink_count == 2
    assert outcome.manifest_path is None
    assert not (Path(outcome.destination or "")).exists()


def test_apply_captures_manifest_checksums_and_provenance(source_root: Path) -> None:
    outcome = capture_backup(source_root, apply=True)

    assert outcome.ok
    assert not outcome.dry_run
    assert outcome.manifest_path is not None
    backup_root = Path(outcome.destination or "")
    manifest = json.loads((backup_root / "MANIFEST.json").read_text("utf-8"))
    assert manifest["backup_id"] == outcome.backup_id
    assert manifest["member_count"] == 5

    sums_text = (backup_root / "SHA256SUMS").read_text("utf-8")
    assert "file.txt" in sums_text
    assert "sub/data.sqlite" in sums_text

    provenance = json.loads((backup_root / "provenance.json").read_text("utf-8"))
    assert provenance["run_id"] == outcome.backup_id
    assert provenance["sase_version"]["packages"]


def test_apply_preserves_file_mode(source_root: Path) -> None:
    outcome = capture_backup(source_root, apply=True)

    payload = Path(outcome.destination or "") / "payload"
    mode = stat.S_IMODE((payload / "file.txt").stat().st_mode)
    assert mode == 0o640


def test_apply_preserves_symlink_without_dereferencing(source_root: Path) -> None:
    outcome = capture_backup(source_root, apply=True)

    payload = Path(outcome.destination or "") / "payload"
    link = payload / "link.txt"
    assert link.is_symlink()
    assert os.readlink(link) == "file.txt"

    dangling = payload / "dangling.txt"
    assert dangling.is_symlink()
    assert os.readlink(dangling) == "does-not-exist.txt"


def test_apply_backs_up_sqlite_with_verified_integrity(source_root: Path) -> None:
    outcome = capture_backup(source_root, apply=True)

    payload = Path(outcome.destination or "") / "payload"
    conn = sqlite3.connect(payload / "sub" / "data.sqlite")
    try:
        rows = conn.execute("SELECT x FROM t").fetchall()
    finally:
        conn.close()
    assert rows == [(1,)]

    manifest = json.loads(
        (Path(outcome.destination or "") / "MANIFEST.json").read_text("utf-8")
    )
    sqlite_member = next(
        member
        for member in manifest["members"]
        if member["relative_path"] == "sub/data.sqlite"
    )
    assert sqlite_member["integrity_check"] == "ok"
    assert sqlite_member["hot_copy"] is True


def test_refuses_when_free_space_is_insufficient(
    source_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tiny_usage = shutil.disk_usage(source_root.parent)._replace(free=1)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: tiny_usage)

    outcome = capture_backup(source_root, apply=True)

    assert not outcome.ok
    assert any("insufficient free space" in error for error in outcome.errors)
    assert outcome.manifest_path is None


def test_refuses_when_cutover_root_is_not_contained(
    source_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(fake_home / ".sase" / "cutover"))

    outcome = capture_backup(source_root, apply=True)

    assert not outcome.ok
    assert not outcome.backup_root_contained
    assert any("not contained" in error for error in outcome.errors)


def test_refuses_when_root_does_not_exist(tmp_path: Path) -> None:
    outcome = capture_backup(tmp_path / "does-not-exist", apply=True)

    assert not outcome.ok
    assert outcome.backup_id == ""


def test_secondary_copy_is_written_when_requested(
    source_root: Path, tmp_path: Path
) -> None:
    secondary = tmp_path / "secondary"
    outcome = capture_backup(source_root, apply=True, secondary=secondary)

    assert outcome.ok
    assert outcome.secondary == str(secondary)
    secondary_backup = secondary / outcome.backup_id
    assert (secondary_backup / "MANIFEST.json").is_file()
    assert (secondary_backup / "payload" / "file.txt").is_file()


def test_dry_run_records_no_secondary_when_omitted(source_root: Path) -> None:
    outcome = capture_backup(source_root, apply=False)
    assert outcome.secondary is None

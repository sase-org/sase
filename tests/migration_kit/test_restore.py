"""Tests for the migration kit's staged restore engine."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.migration_kit.backup import capture_backup
from sase.migration_kit.paths import CUTOVER_BACKUP_DIR_ENV_VAR, backup_payload_dir
from sase.migration_kit.restore import restore_backup


@pytest.fixture(autouse=True)
def _cutover_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cutover"
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(root))
    return root


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "file.txt").write_text("hello world", encoding="utf-8")
    return root


def _backup_id(source_root: Path) -> str:
    outcome = capture_backup(source_root, apply=True)
    assert outcome.ok
    return outcome.backup_id


def test_restore_dry_run_verifies_and_stages_without_touching_live_root(
    source_root: Path,
) -> None:
    backup_id = _backup_id(source_root)
    original_contents = (source_root / "file.txt").read_text("utf-8")

    outcome = restore_backup(backup_id, apply=False)

    assert outcome.ok
    assert outcome.dry_run
    assert not outcome.applied
    assert Path(outcome.staging_path).is_dir()
    assert (Path(outcome.staging_path) / "file.txt").read_text("utf-8") == (
        original_contents
    )
    assert (source_root / "file.txt").read_text("utf-8") == original_contents


def test_restore_reports_diff_against_modified_live_root(source_root: Path) -> None:
    backup_id = _backup_id(source_root)
    (source_root / "file.txt").write_text("changed", encoding="utf-8")
    (source_root / "new.txt").write_text("new", encoding="utf-8")

    outcome = restore_backup(backup_id, apply=False)

    assert outcome.diff_changed == ("file.txt",)
    assert outcome.diff_removed == ("new.txt",)
    assert outcome.diff_added == ()


def test_restore_refuses_on_checksum_mismatch_without_staging(
    source_root: Path,
) -> None:
    backup_id = _backup_id(source_root)
    tampered = backup_payload_dir(backup_id) / "file.txt"
    tampered.write_text("tampered", encoding="utf-8")

    outcome = restore_backup(backup_id, apply=False)

    assert not outcome.ok
    assert outcome.checksum_failures
    assert outcome.staging_path == ""


def test_restore_reports_ownership_deltas(source_root: Path) -> None:
    backup_id = _backup_id(source_root)
    manifest_path = backup_payload_dir(backup_id).parent / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for member in manifest["members"]:
        if member["relative_path"] == "file.txt":
            member["uid"] = member["uid"] + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    outcome = restore_backup(backup_id, apply=False)

    assert outcome.ok
    assert len(outcome.ownership_deltas) == 1
    delta = outcome.ownership_deltas[0]
    assert delta.relative_path == "file.txt"
    assert delta.live_uid == os.getuid()


def test_restore_apply_swaps_staged_copy_and_preserves_live_root(
    source_root: Path,
) -> None:
    backup_id = _backup_id(source_root)
    (source_root / "file.txt").write_text("changed", encoding="utf-8")
    (source_root / "new.txt").write_text("new", encoding="utf-8")

    outcome = restore_backup(backup_id, apply=True)

    assert outcome.ok
    assert outcome.applied
    assert (source_root / "file.txt").read_text("utf-8") == "hello world"
    assert not (source_root / "new.txt").exists()

    preserved_candidates = list(
        source_root.parent.glob(f"{source_root.name}.pre-restore-*")
    )
    assert len(preserved_candidates) == 1
    assert (preserved_candidates[0] / "new.txt").read_text("utf-8") == "new"

    # The backup itself is never modified or deleted by a restore.
    assert backup_payload_dir(backup_id).is_dir()
    assert (backup_payload_dir(backup_id) / "file.txt").read_text("utf-8") == (
        "hello world"
    )


def test_restore_missing_backup_id_reports_error() -> None:
    outcome = restore_backup("does-not-exist", apply=False)

    assert not outcome.ok
    assert outcome.errors

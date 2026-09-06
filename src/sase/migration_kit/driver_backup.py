"""Backup-record helpers for the migration driver.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.migration_kit.hashing import sha256_file
from sase.migration_kit.manifest import BackupManifest
from sase.migration_kit.paths import backup_dir, backup_payload_dir


def backup_record(
    backup_id: str,
    *,
    operation_entry: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = backup_dir(backup_id) / "MANIFEST.json"
    if not manifest_path.is_file():
        return {
            "schema_version": 1,
            "backup_id": backup_id,
            "root": "",
            "location": str(backup_dir(backup_id)),
            "verified": False,
            "checksum_manifest": str(backup_dir(backup_id) / "SHA256SUMS"),
        }
    manifest = BackupManifest.from_dict(json.loads(manifest_path.read_text("utf-8")))
    checksum_failures = _verify_backup_checksums(backup_id, manifest)
    sqlite_checks = {
        member.relative_path: member.integrity_check
        for member in manifest.members
        if member.integrity_check is not None
    }
    return {
        "schema_version": 1,
        "backup_id": backup_id,
        "root": manifest.resolved_source_root,
        "location": str(backup_dir(backup_id)),
        "verified": not checksum_failures,
        "checksum_manifest": str(backup_dir(backup_id) / "SHA256SUMS"),
        "source_digest": operation_entry.get("source_digests", {}).get(
            manifest.resolved_source_root
        ),
        "secondary_location": manifest.secondary,
        "source_size_bytes": manifest.total_size_bytes,
        "stored_size_bytes": _stored_size(backup_payload_dir(backup_id)),
        "created_at": manifest.created_at,
        "sqlite_integrity_checks": sqlite_checks,
    }


def _stored_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(
        child.stat().st_size
        for child in path.rglob("*")
        if child.is_file() and not child.is_symlink()
    )


def _verify_backup_checksums(backup_id: str, manifest: BackupManifest) -> list[str]:
    payload_dir = backup_payload_dir(backup_id)
    failures: list[str] = []
    for member in manifest.members:
        if member.sha256 is None:
            continue
        member_path = payload_dir / member.relative_path
        if not member_path.is_file():
            failures.append(f"{member.relative_path}: missing from payload")
            continue
        actual = sha256_file(member_path)
        if actual != member.sha256:
            failures.append(
                f"{member.relative_path}: expected {member.sha256}, got {actual}"
            )
    return failures

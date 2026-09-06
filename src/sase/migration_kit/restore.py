"""Staged restore with checksum verification and ownership-delta reporting.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets
import shutil
from typing import Any

from sase.core.time import local_now
from sase.migration_kit.hashing import sha256_file
from sase.migration_kit.manifest import BackupManifest
from sase.migration_kit.paths import backup_dir, backup_payload_dir, restores_dir


@dataclass(frozen=True)
class _OwnershipDelta:
    """A member whose backed-up owner differs from the live filesystem's."""

    relative_path: str
    backed_up_uid: int | None
    backed_up_gid: int | None
    live_uid: int | None
    live_gid: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "backed_up_uid": self.backed_up_uid,
            "backed_up_gid": self.backed_up_gid,
            "live_uid": self.live_uid,
            "live_gid": self.live_gid,
        }


@dataclass(frozen=True)
class RestoreOutcome:
    """The result of ``sase migrate restore``, in dry-run or apply mode."""

    ok: bool
    dry_run: bool
    backup_id: str
    staging_path: str
    live_root: str
    applied: bool
    verified_member_count: int
    checksum_failures: tuple[str, ...] = field(default_factory=tuple)
    ownership_deltas: tuple[_OwnershipDelta, ...] = field(default_factory=tuple)
    diff_added: tuple[str, ...] = field(default_factory=tuple)
    diff_removed: tuple[str, ...] = field(default_factory=tuple)
    diff_changed: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "backup_id": self.backup_id,
            "staging_path": self.staging_path,
            "live_root": self.live_root,
            "applied": self.applied,
            "verified_member_count": self.verified_member_count,
            "checksum_failures": list(self.checksum_failures),
            "ownership_deltas": [delta.to_dict() for delta in self.ownership_deltas],
            "diff_added": list(self.diff_added),
            "diff_removed": list(self.diff_removed),
            "diff_changed": list(self.diff_changed),
            "errors": list(self.errors),
        }


def _load_manifest(backup_id: str) -> BackupManifest | None:
    manifest_path = backup_dir(backup_id) / "MANIFEST.json"
    if not manifest_path.is_file():
        return None
    return BackupManifest.from_dict(json.loads(manifest_path.read_text("utf-8")))


def _verify_checksums(backup_id: str, manifest: BackupManifest) -> list[str]:
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


def _compute_ownership_deltas(
    manifest: BackupManifest, live_root: Path
) -> list[_OwnershipDelta]:
    deltas: list[_OwnershipDelta] = []
    for member in manifest.members:
        if member.uid is None and member.gid is None:
            continue
        live_path = live_root / member.relative_path
        if not (live_path.exists() or live_path.is_symlink()):
            continue
        live_stat = live_path.lstat()
        if live_stat.st_uid != member.uid or live_stat.st_gid != member.gid:
            deltas.append(
                _OwnershipDelta(
                    relative_path=member.relative_path,
                    backed_up_uid=member.uid,
                    backed_up_gid=member.gid,
                    live_uid=live_stat.st_uid,
                    live_gid=live_stat.st_gid,
                )
            )
    return deltas


def _diff_against_live(
    manifest: BackupManifest, live_root: Path
) -> tuple[list[str], list[str], list[str]]:
    staged_paths = {member.relative_path for member in manifest.members}
    live_paths: set[str] = set()
    if live_root.is_dir():
        for entry in live_root.rglob("*"):
            live_paths.add(entry.relative_to(live_root).as_posix())

    added = sorted(staged_paths - live_paths)
    removed = sorted(live_paths - staged_paths)
    changed: list[str] = []
    for member in manifest.members:
        if member.sha256 is None or member.relative_path not in live_paths:
            continue
        live_path = live_root / member.relative_path
        if live_path.is_file() and sha256_file(live_path) != member.sha256:
            changed.append(member.relative_path)
    return added, removed, changed


def restore_backup(
    backup_id: str,
    *,
    apply: bool,
    live_root: Path | None = None,
) -> RestoreOutcome:
    """Verify and stage a restore of *backup_id*, swapping into place if *apply*.

    Checksums are verified against ``SHA256SUMS``/``MANIFEST.json`` before
    anything else happens. A staging copy is always produced under the
    cutover root; ``apply`` additionally moves the live root aside (never
    deleting it) and swaps the staged copy into its place. The backup itself
    is never deleted or modified by a restore.
    """
    manifest = _load_manifest(backup_id)
    if manifest is None:
        return RestoreOutcome(
            ok=False,
            dry_run=not apply,
            backup_id=backup_id,
            staging_path="",
            live_root=str(live_root) if live_root else "",
            applied=False,
            verified_member_count=0,
            errors=(f"no MANIFEST.json found for backup id {backup_id}",),
        )

    resolved_live_root = (
        live_root.expanduser().resolve()
        if live_root is not None
        else Path(manifest.resolved_source_root)
    )

    checksum_failures = _verify_checksums(backup_id, manifest)
    if checksum_failures:
        return RestoreOutcome(
            ok=False,
            dry_run=not apply,
            backup_id=backup_id,
            staging_path="",
            live_root=str(resolved_live_root),
            applied=False,
            verified_member_count=len(manifest.members) - len(checksum_failures),
            checksum_failures=tuple(checksum_failures),
            errors=("checksum verification failed; nothing was staged",),
        )

    ownership_deltas = _compute_ownership_deltas(manifest, resolved_live_root)
    diff_added, diff_removed, diff_changed = _diff_against_live(
        manifest, resolved_live_root
    )

    staging_path = restores_dir() / (
        f"{backup_id}-{local_now().strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"
    )
    payload_dir = backup_payload_dir(backup_id)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(payload_dir, staging_path, symlinks=True)

    applied = False
    errors: list[str] = []
    if apply:
        applied, apply_errors = _swap_into_place(staging_path, resolved_live_root)
        errors.extend(apply_errors)

    return RestoreOutcome(
        ok=not errors,
        dry_run=not apply,
        backup_id=backup_id,
        staging_path=str(staging_path),
        live_root=str(resolved_live_root),
        applied=applied,
        verified_member_count=len(manifest.members),
        checksum_failures=(),
        ownership_deltas=tuple(ownership_deltas),
        diff_added=tuple(diff_added),
        diff_removed=tuple(diff_removed),
        diff_changed=tuple(diff_changed),
        errors=tuple(errors),
    )


def _swap_into_place(staging_path: Path, live_root: Path) -> tuple[bool, list[str]]:
    """Move *live_root* aside (never deleting it) and swap the staged copy in."""
    errors: list[str] = []
    if live_root.exists() or live_root.is_symlink():
        preserved = live_root.with_name(
            f"{live_root.name}.pre-restore-{local_now().strftime('%Y%m%dT%H%M%S')}"
        )
        try:
            os.rename(live_root, preserved)
        except OSError as exc:
            errors.append(f"failed to move aside live root {live_root}: {exc}")
            return False, errors
    live_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(staging_path), str(live_root))
    except OSError as exc:
        errors.append(f"failed to swap staged restore into {live_root}: {exc}")
        return False, errors
    return True, errors

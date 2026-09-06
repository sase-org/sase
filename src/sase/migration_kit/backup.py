"""Quiescent, checksummed, SQLite-consistent backup capture.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
from typing import Any

from sase.core.time import local_now
from sase.migration_kit.hashing import directory_total_size, sha256_file
from sase.migration_kit.manifest import (
    BACKUP_MANIFEST_SCHEMA_VERSION,
    BackupManifest,
    BackupMemberRecord,
)
from sase.migration_kit.paths import (
    backup_dir,
    backup_payload_dir,
    backups_dir,
    is_contained_backup_root,
)
from sase.migration_kit.provenance import build_provenance, host_identity
from sase.migration_kit.sqlite_backup import (
    backup_sqlite_file,
    looks_like_sqlite_extension,
    looks_like_sqlite_file,
)

FREE_SPACE_SAFETY_FACTOR = 1.15


@dataclass(frozen=True)
class BackupOutcome:
    """The result of ``sase migrate backup``, in dry-run or apply mode."""

    ok: bool
    dry_run: bool
    backup_id: str
    root: str
    resolved_root: str
    destination: str | None
    secondary: str | None
    total_size_bytes: int
    required_bytes: int
    free_bytes: int
    member_count: int
    sqlite_member_count: int
    symlink_count: int
    backup_root_contained: bool
    manifest_path: str | None
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "backup_id": self.backup_id,
            "root": self.root,
            "resolved_root": self.resolved_root,
            "destination": self.destination,
            "secondary": self.secondary,
            "total_size_bytes": self.total_size_bytes,
            "required_bytes": self.required_bytes,
            "free_bytes": self.free_bytes,
            "member_count": self.member_count,
            "sqlite_member_count": self.sqlite_member_count,
            "symlink_count": self.symlink_count,
            "backup_root_contained": self.backup_root_contained,
            "manifest_path": self.manifest_path,
            "errors": list(self.errors),
        }


def _generate_backup_id() -> str:
    timestamp = local_now().strftime("%Y%m%dT%H%M%S")
    return f"{host_identity()}-{timestamp}-{secrets.token_hex(3)}"


def capture_backup(
    root: Path,
    *,
    apply: bool,
    secondary: Path | None = None,
) -> BackupOutcome:
    """Capture a verified backup of *root*.

    A dry run (``apply=False``) measures the source, checks free space, and
    reports what an apply would do without writing anything. An apply walks
    *root*, copying every SQLite store through the online backup API (never
    reading its live bytes directly), preserving modes/mtimes/symlinks
    without dereferencing, and recording a checksum manifest plus provenance.
    """
    errors: list[str] = []
    resolved_root = root.expanduser().resolve()
    if not resolved_root.is_dir():
        return BackupOutcome(
            ok=False,
            dry_run=not apply,
            backup_id="",
            root=str(root),
            resolved_root=str(resolved_root),
            destination=None,
            secondary=str(secondary) if secondary else None,
            total_size_bytes=0,
            required_bytes=0,
            free_bytes=0,
            member_count=0,
            sqlite_member_count=0,
            symlink_count=0,
            backup_root_contained=is_contained_backup_root(backups_dir()),
            manifest_path=None,
            errors=(f"root does not exist or is not a directory: {resolved_root}",),
        )

    total_size = directory_total_size(resolved_root)
    required_bytes = int(total_size * FREE_SPACE_SAFETY_FACTOR)
    destination_root = backups_dir()
    usage = shutil.disk_usage(destination_root)
    backup_root_contained = is_contained_backup_root(destination_root)
    if not backup_root_contained:
        errors.append(
            f"cutover backup root {destination_root} is not contained outside "
            "every SASE runtime root"
        )

    if usage.free < required_bytes:
        errors.append(
            f"insufficient free space at {destination_root}: need "
            f"{required_bytes} bytes ({total_size} bytes x "
            f"{FREE_SPACE_SAFETY_FACTOR}), have {usage.free} bytes"
        )

    entries = sorted(resolved_root.rglob("*"))
    sqlite_count = sum(
        1
        for entry in entries
        if not entry.is_symlink()
        and entry.is_file()
        and looks_like_sqlite_extension(entry)
        and looks_like_sqlite_file(entry)
    )
    symlink_count = sum(1 for entry in entries if entry.is_symlink())
    member_count = len(entries)

    if errors:
        return BackupOutcome(
            ok=False,
            dry_run=not apply,
            backup_id="",
            root=str(root),
            resolved_root=str(resolved_root),
            destination=str(destination_root),
            secondary=str(secondary) if secondary else None,
            total_size_bytes=total_size,
            required_bytes=required_bytes,
            free_bytes=usage.free,
            member_count=member_count,
            sqlite_member_count=sqlite_count,
            symlink_count=symlink_count,
            backup_root_contained=backup_root_contained,
            manifest_path=None,
            errors=tuple(errors),
        )

    backup_id = _generate_backup_id()
    if not apply:
        return BackupOutcome(
            ok=True,
            dry_run=True,
            backup_id=backup_id,
            root=str(root),
            resolved_root=str(resolved_root),
            destination=str(backup_dir(backup_id)),
            secondary=str(secondary) if secondary else None,
            total_size_bytes=total_size,
            required_bytes=required_bytes,
            free_bytes=usage.free,
            member_count=member_count,
            sqlite_member_count=sqlite_count,
            symlink_count=symlink_count,
            backup_root_contained=backup_root_contained,
            manifest_path=None,
            errors=(),
        )

    return _apply_backup(
        root=root,
        resolved_root=resolved_root,
        entries=entries,
        backup_id=backup_id,
        total_size=total_size,
        required_bytes=required_bytes,
        free_bytes=usage.free,
        backup_root_contained=backup_root_contained,
        secondary=secondary,
    )


def _apply_backup(
    *,
    root: Path,
    resolved_root: Path,
    entries: list[Path],
    backup_id: str,
    total_size: int,
    required_bytes: int,
    free_bytes: int,
    backup_root_contained: bool,
    secondary: Path | None,
) -> BackupOutcome:
    payload_dir = backup_payload_dir(backup_id)
    payload_dir.mkdir(parents=True, exist_ok=True)

    members: list[BackupMemberRecord] = []
    errors: list[str] = []
    sqlite_count = 0
    symlink_count = 0

    for source_entry in entries:
        relative = source_entry.relative_to(resolved_root)
        destination_entry = payload_dir / relative
        try:
            member = _capture_member(source_entry, destination_entry, relative)
        except OSError as exc:
            errors.append(f"failed to capture {relative}: {exc}")
            continue
        members.append(member)
        if member.kind == "sqlite":
            sqlite_count += 1
            if member.integrity_check != "ok":
                errors.append(
                    f"sqlite integrity_check failed for {relative}: "
                    f"{member.integrity_check}"
                )
        elif member.kind == "symlink":
            symlink_count += 1

    checksums = {
        member.relative_path: member.sha256
        for member in members
        if member.sha256 is not None
    }
    (backup_dir(backup_id) / "SHA256SUMS").write_text(
        "".join(
            f"{digest}  {relative_path}\n"
            for relative_path, digest in sorted(checksums.items())
        ),
        encoding="utf-8",
    )

    manifest = BackupManifest(
        schema_version=BACKUP_MANIFEST_SCHEMA_VERSION,
        backup_id=backup_id,
        host=host_identity(),
        created_at=local_now().isoformat(),
        source_root=str(root),
        resolved_source_root=str(resolved_root),
        backup_root_contained=backup_root_contained,
        secondary=str(secondary) if secondary else None,
        total_size_bytes=total_size,
        members=tuple(members),
    )
    manifest_path = backup_dir(backup_id) / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    provenance = build_provenance(
        run_id=backup_id,
        source_root=root,
        resolved_source_root=resolved_root,
    )
    (backup_dir(backup_id) / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if secondary is not None:
        secondary_dir = secondary.expanduser() / backup_id
        shutil.copytree(backup_dir(backup_id), secondary_dir, symlinks=True)

    return BackupOutcome(
        ok=not errors,
        dry_run=False,
        backup_id=backup_id,
        root=str(root),
        resolved_root=str(resolved_root),
        destination=str(backup_dir(backup_id)),
        secondary=str(secondary) if secondary else None,
        total_size_bytes=total_size,
        required_bytes=required_bytes,
        free_bytes=free_bytes,
        member_count=len(members),
        sqlite_member_count=sqlite_count,
        symlink_count=symlink_count,
        backup_root_contained=backup_root_contained,
        manifest_path=str(manifest_path),
        errors=tuple(errors),
    )


def _capture_member(
    source: Path, destination: Path, relative: Path
) -> BackupMemberRecord:
    relative_str = relative.as_posix()
    lstat_result = source.lstat()

    if source.is_symlink():
        target = os.readlink(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        os.symlink(target, destination)
        return BackupMemberRecord(
            relative_path=relative_str,
            kind="symlink",
            size=0,
            sha256=None,
            symlink_target=target,
            mode=None,
            uid=lstat_result.st_uid,
            gid=lstat_result.st_gid,
        )

    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        os.chmod(destination, stat.S_IMODE(lstat_result.st_mode))
        return BackupMemberRecord(
            relative_path=relative_str,
            kind="dir",
            size=0,
            sha256=None,
            symlink_target=None,
            mode=stat.S_IMODE(lstat_result.st_mode),
            uid=lstat_result.st_uid,
            gid=lstat_result.st_gid,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    is_sqlite = looks_like_sqlite_extension(source) and looks_like_sqlite_file(source)
    integrity_check: str | None = None
    hot_copy: bool | None = None
    if is_sqlite:
        result = backup_sqlite_file(source, destination)
        integrity_check = result.integrity_check
        hot_copy = result.hot_copy
    else:
        shutil.copy2(source, destination)
    os.chmod(destination, stat.S_IMODE(lstat_result.st_mode))
    digest = sha256_file(destination)
    return BackupMemberRecord(
        relative_path=relative_str,
        kind="sqlite" if is_sqlite else "file",
        size=destination.stat().st_size,
        sha256=digest,
        symlink_target=None,
        mode=stat.S_IMODE(lstat_result.st_mode),
        uid=lstat_result.st_uid,
        gid=lstat_result.st_gid,
        integrity_check=integrity_check,
        hot_copy=hot_copy,
    )

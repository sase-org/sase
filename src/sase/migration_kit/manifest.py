"""Backup manifest, checksum, and provenance record shapes.

TEMPORARY MODULE: deletion owner sase-x7.14.

These are plain Python dataclasses, not the Rust ``MigrationBackupRecord``
wire type ``kit-contract`` added to ``sase_core``: the ``migration_*``
bindings are not yet published on a released ``sase-core-rs`` (see the
``sase-x7.2.1.1`` follow-up), so this module cannot call through them without
either importing an unpublished binding or vendoring a Python
reimplementation of the wire contract -- both forbidden. ``kit-driver``
reconciles this on-disk shape with ``MigrationBackupRecord`` once a core
release exposes the bindings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BACKUP_MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BackupMemberRecord:
    """One filesystem entry captured into a backup's payload tree."""

    relative_path: str
    kind: str  # "dir" | "file" | "sqlite" | "symlink"
    size: int
    sha256: str | None
    symlink_target: str | None
    mode: int | None
    uid: int | None
    gid: int | None
    integrity_check: str | None = None
    hot_copy: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind,
            "size": self.size,
            "sha256": self.sha256,
            "symlink_target": self.symlink_target,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "integrity_check": self.integrity_check,
            "hot_copy": self.hot_copy,
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> BackupMemberRecord:
        return BackupMemberRecord(
            relative_path=str(payload["relative_path"]),
            kind=str(payload["kind"]),
            size=int(payload["size"]),
            sha256=payload.get("sha256"),
            symlink_target=payload.get("symlink_target"),
            mode=payload.get("mode"),
            uid=payload.get("uid"),
            gid=payload.get("gid"),
            integrity_check=payload.get("integrity_check"),
            hot_copy=payload.get("hot_copy"),
        )


@dataclass(frozen=True)
class BackupManifest:
    """The ``MANIFEST.json`` recorded alongside every captured backup."""

    schema_version: int
    backup_id: str
    host: str
    created_at: str
    source_root: str
    resolved_source_root: str
    backup_root_contained: bool
    secondary: str | None
    total_size_bytes: int
    members: tuple[BackupMemberRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backup_id": self.backup_id,
            "host": self.host,
            "created_at": self.created_at,
            "source_root": self.source_root,
            "resolved_source_root": self.resolved_source_root,
            "backup_root_contained": self.backup_root_contained,
            "secondary": self.secondary,
            "total_size_bytes": self.total_size_bytes,
            "member_count": len(self.members),
            "members": [member.to_dict() for member in self.members],
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> BackupManifest:
        return BackupManifest(
            schema_version=int(payload["schema_version"]),
            backup_id=str(payload["backup_id"]),
            host=str(payload["host"]),
            created_at=str(payload["created_at"]),
            source_root=str(payload["source_root"]),
            resolved_source_root=str(payload["resolved_source_root"]),
            backup_root_contained=bool(payload["backup_root_contained"]),
            secondary=payload.get("secondary"),
            total_size_bytes=int(payload["total_size_bytes"]),
            members=tuple(
                BackupMemberRecord.from_dict(member)
                for member in payload.get("members", [])
            ),
        )

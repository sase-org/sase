"""Wire models for journaled ACE-run trash batches and outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class AceRunTrashItemOutcome:
    """One quarantined, kept, or skipped run directory."""

    artifact_dir: str
    project: str
    timestamp: str
    outcome: str
    reasons: tuple[str, ...] = ()
    detail: str | None = None
    bytes: int = 0
    original_path: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "artifact_dir": self.artifact_dir,
            "project": self.project,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "detail": self.detail,
            "bytes": self.bytes,
            "original_path": self.original_path,
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> AceRunTrashItemOutcome:
        original_path = str(payload.get("original_path") or "")
        artifact_dir = str(payload.get("artifact_dir") or original_path or "")
        return cls(
            artifact_dir=artifact_dir,
            project=str(payload.get("project") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            outcome=str(payload.get("outcome") or ""),
            reasons=tuple(str(reason) for reason in payload.get("reasons") or ()),
            detail=(None if payload.get("detail") is None else str(payload["detail"])),
            bytes=int(payload.get("bytes") or 0),
            original_path=original_path,
        )


@dataclass(frozen=True)
class AceRunTrashBatch:
    """One journaled trash batch."""

    id: str
    created_at: str
    status: str
    run_count: int
    bytes: int
    projects: tuple[str, ...]
    orphan_items: tuple[AceRunTrashItemOutcome, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "status": self.status,
            "run_count": self.run_count,
            "bytes": self.bytes,
            "projects": list(self.projects),
            "orphan_items": [item.to_json_dict() for item in self.orphan_items],
        }

    @classmethod
    def from_json_dict(cls, payload: Mapping[str, Any]) -> AceRunTrashBatch:
        return cls(
            id=str(payload.get("id") or ""),
            created_at=str(payload.get("created_at") or ""),
            status=str(payload.get("status") or ""),
            run_count=int(payload.get("run_count") or 0),
            bytes=int(payload.get("bytes") or 0),
            projects=tuple(str(p) for p in payload.get("projects") or ()),
            orphan_items=tuple(
                AceRunTrashItemOutcome.from_json_dict(item)
                for item in payload.get("orphan_items") or ()
            ),
        )


@dataclass(frozen=True)
class AceRunTrashQuarantineResult:
    """Outcome of quarantining reviewed runs into restorable trash."""

    batch_id: str
    status: str
    requested: int
    quarantined: int
    kept: int
    not_reviewed: int
    errors: int
    bytes_quarantined: int
    blocked_reason: str | None
    items: tuple[AceRunTrashItemOutcome, ...]
    kept_by_reason: dict[str, int]
    removed_empty_shards: int
    journal_path: str
    deindexed: int
    index_errors: tuple[str, ...]
    restorable_until: str
    created_at: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "status": self.status,
            "requested": self.requested,
            "quarantined": self.quarantined,
            "kept": self.kept,
            "not_reviewed": self.not_reviewed,
            "errors": self.errors,
            "bytes_quarantined": self.bytes_quarantined,
            "blocked_reason": self.blocked_reason,
            "items": [item.to_json_dict() for item in self.items],
            "kept_by_reason": dict(self.kept_by_reason),
            "removed_empty_shards": self.removed_empty_shards,
            "journal_path": self.journal_path,
            "deindexed": self.deindexed,
            "index_errors": list(self.index_errors),
            "restorable_until": self.restorable_until,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AceRunTrashListResult:
    """Newest-first listing of journaled trash batches."""

    batches: tuple[AceRunTrashBatch, ...]
    unreadable_journal_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "batches": [batch.to_json_dict() for batch in self.batches],
            "unreadable_journal_count": self.unreadable_journal_count,
        }


@dataclass(frozen=True)
class AceRunTrashRestoreResult:
    """Outcome of restoring a trash batch back into the projects tree."""

    batch_id: str
    status: str
    restored: int
    conflicts: int
    errors: int
    restored_dirs: tuple[str, ...]
    items: tuple[AceRunTrashItemOutcome, ...]
    blocked_reason: str | None
    reindexed: int
    index_errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "status": self.status,
            "restored": self.restored,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "restored_dirs": list(self.restored_dirs),
            "items": [item.to_json_dict() for item in self.items],
            "blocked_reason": self.blocked_reason,
            "reindexed": self.reindexed,
            "index_errors": list(self.index_errors),
        }


@dataclass(frozen=True)
class AceRunTrashPurgeResult:
    """Outcome of permanently purging expired trash batches."""

    status: str
    purged: int
    kept: int
    restored: int
    errors: int
    freed_bytes: int
    restored_dirs: tuple[str, ...]
    purged_batches: tuple[str, ...]
    items: tuple[AceRunTrashItemOutcome, ...]
    blocked_reason: str | None
    reindexed: int
    index_errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
            "status": self.status,
            "purged": self.purged,
            "kept": self.kept,
            "restored": self.restored,
            "errors": self.errors,
            "freed_bytes": self.freed_bytes,
            "restored_dirs": list(self.restored_dirs),
            "purged_batches": list(self.purged_batches),
            "items": [item.to_json_dict() for item in self.items],
            "blocked_reason": self.blocked_reason,
            "reindexed": self.reindexed,
            "index_errors": list(self.index_errors),
        }


@dataclass(frozen=True)
class ReviewedRunSet:
    """Reviewed run dirs loaded from a snapshot, keyed by canonical dir."""

    fingerprint: str
    dirs: frozenset[str] = field(default_factory=frozenset)


__all__ = [
    "AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION",
    "AceRunTrashBatch",
    "AceRunTrashItemOutcome",
    "AceRunTrashListResult",
    "AceRunTrashPurgeResult",
    "AceRunTrashQuarantineResult",
    "AceRunTrashRestoreResult",
    "ReviewedRunSet",
]

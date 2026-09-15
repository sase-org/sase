"""Data models for ACE-run artifact-directory retention."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir


DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS = 2
ACE_RUN_RETENTION_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class AceRunProtectionSnapshot:
    """Run-retention protections collected from durable reference sources."""

    protected_dirs: frozenset[str] = frozenset()
    protected_agent_names: frozenset[str] = frozenset()
    protected_timestamps: frozenset[str] = frozenset()
    non_closed_bead_ids_by_project: dict[str, frozenset[str]] = field(
        default_factory=dict
    )
    sources_scanned: tuple[str, ...] = ()
    sources_unavailable: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "protected_dirs": sorted(self.protected_dirs),
            "protected_agent_names": sorted(self.protected_agent_names),
            "protected_timestamps": sorted(self.protected_timestamps),
            "non_closed_bead_ids_by_project": {
                project: sorted(ids)
                for project, ids in sorted(self.non_closed_bead_ids_by_project.items())
            },
            "sources_scanned": list(self.sources_scanned),
            "sources_unavailable": list(self.sources_unavailable),
        }


@dataclass(frozen=True)
class AceRunRetentionPolicy:
    """Inputs that make an ACE-run retention plan deterministic."""

    now: datetime
    keep_recent_months: int = DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS
    project: str | None = None
    limit: int | None = None
    projects_root: Path | str | None = None

    def normalized_projects_root(self) -> Path:
        if self.projects_root:
            return Path(self.projects_root).expanduser()
        return sase_projects_dir()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "now": self.now.isoformat(),
            "keep_recent_months": self.keep_recent_months,
            "project": self.project,
            "limit": self.limit,
            "projects_root": str(self.normalized_projects_root()),
        }


@dataclass(frozen=True)
class AceRunRetentionItem:
    """One terminal ACE-run directory selected for reclamation."""

    project: str
    timestamp: str
    artifact_dir: str
    size_bytes: int
    reason: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "timestamp": self.timestamp,
            "artifact_dir": self.artifact_dir,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProtectedAceRunItem:
    """One ACE-run directory preserved by a retention guard."""

    project: str
    timestamp: str
    artifact_dir: str
    reasons: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "timestamp": self.timestamp,
            "artifact_dir": self.artifact_dir,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EmptyAceRunShard:
    """One empty month/day shard that falls outside the startup watch window."""

    project: str
    path: str
    kind: str
    reason: str

    def to_json_dict(self) -> dict[str, str]:
        return {
            "project": self.project,
            "path": self.path,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AceRunRetentionCounts:
    """Small counter summary for retention UI and chops."""

    candidates: int
    selected: int
    protected: int
    empty_out_of_range_shards: int
    truncated: int

    def to_json_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "selected": self.selected,
            "protected": self.protected,
            "empty_out_of_range_shards": self.empty_out_of_range_shards,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class AceRunRetentionPlan:
    """Dry-run-first plan for reclaiming ACE-run directories."""

    policy: AceRunRetentionPolicy
    protections: AceRunProtectionSnapshot
    selected: tuple[AceRunRetentionItem, ...]
    protected: tuple[ProtectedAceRunItem, ...]
    empty_out_of_range_shards: tuple[EmptyAceRunShard, ...]
    counts: AceRunRetentionCounts
    reclaimable_bytes: int
    sources_unavailable: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ACE_RUN_RETENTION_SCHEMA_VERSION,
            "policy": self.policy.to_json_dict(),
            "protections": self.protections.to_json_dict(),
            "selected": [item.to_json_dict() for item in self.selected],
            "protected": [item.to_json_dict() for item in self.protected],
            "empty_out_of_range_shards": [
                item.to_json_dict() for item in self.empty_out_of_range_shards
            ],
            "counts": self.counts.to_json_dict(),
            "reclaimable_bytes": self.reclaimable_bytes,
            "sources_unavailable": list(self.sources_unavailable),
        }


@dataclass(frozen=True)
class AceRunRetentionApplyResult:
    """Outcome of applying a previously inspected retention plan."""

    removed_runs: int
    removed_empty_shards: int
    bytes_reclaimed: int
    deindexed: int
    skipped: tuple[str, ...]
    errors: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "removed_runs": self.removed_runs,
            "removed_empty_shards": self.removed_empty_shards,
            "bytes_reclaimed": self.bytes_reclaimed,
            "deindexed": self.deindexed,
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


__all__ = [
    "ACE_RUN_RETENTION_SCHEMA_VERSION",
    "DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS",
    "AceRunProtectionSnapshot",
    "AceRunRetentionApplyResult",
    "AceRunRetentionCounts",
    "AceRunRetentionItem",
    "AceRunRetentionPlan",
    "AceRunRetentionPolicy",
    "EmptyAceRunShard",
    "ProtectedAceRunItem",
]

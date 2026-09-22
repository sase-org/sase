"""Proc log retention and prune outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import require_wire_schema
from .snapshots import ProcStoreSnapshot


@dataclass(frozen=True)
class ProcLogRetentionEntry:
    """One bounded store-owned proc log retention decision."""

    proc_id: str
    path: str
    status: str
    reason: str
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proc_id": self.proc_id,
            "path": self.path,
            "status": self.status,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ProcLogRetentionResult:
    """Structured outcome from deleting current/rotated store-owned proc logs."""

    log_root: Path
    apply: bool
    scanned: int = 0
    selected: int = 0
    removed: int = 0
    skipped: int = 0
    errors: int = 0
    reclaimable_bytes: int = 0
    reclaimed_bytes: int = 0
    byte_accounting_complete: bool = True
    capped: bool = False
    entries: tuple[ProcLogRetentionEntry, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        if not self.selected:
            return f"nothing eligible under {self.log_root}"
        verb = "removed" if self.apply else "would remove"
        errors = f"; errors={self.errors}" if self.errors else ""
        incomplete = (
            "; byte accounting incomplete" if not self.byte_accounting_complete else ""
        )
        return (
            f"{verb} {self.removed if self.apply else self.selected} proc log "
            f"file(s) under {self.log_root}; scanned={self.scanned}, "
            f"reclaimable={self.reclaimable_bytes}, reclaimed={self.reclaimed_bytes}"
            f"{errors}{incomplete}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_root": str(self.log_root),
            "apply": self.apply,
            "scanned": self.scanned,
            "selected": self.selected,
            "removed": self.removed,
            "skipped": self.skipped,
            "errors": self.errors,
            "reclaimable_bytes": self.reclaimable_bytes,
            "reclaimed_bytes": self.reclaimed_bytes,
            "byte_accounting_complete": self.byte_accounting_complete,
            "capped": self.capped,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class ProcPrunedStateRetention:
    """Best-effort state cleanup outcome for rows pruned from the proc store."""

    log_retention: ProcLogRetentionResult | None = None
    runtime_retention: Any | None = None
    errors: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return (
            bool(self.errors)
            or bool(self.log_retention and self.log_retention.errors)
            or bool(
                self.runtime_retention is not None
                and getattr(self.runtime_retention, "errors", 0)
            )
        )


@dataclass(frozen=True)
class ProcPruneOutcome:
    schema_version: int
    snapshot: ProcStoreSnapshot
    pruned_proc_ids: list[str] = field(default_factory=list)
    pruned_log_proc_ids: list[str] = field(default_factory=list)
    log_retention: ProcLogRetentionResult | None = None
    runtime_retention: Any | None = None
    state_retention: ProcPrunedStateRetention | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcPruneOutcome:
        require_wire_schema(data)
        pruned_proc_ids = [
            str(item)
            for item in (
                data.get("pruned_proc_ids")
                if data.get("pruned_proc_ids") is not None
                else data.get("pruned_task_ids")
            )
            or []
        ]
        return cls(
            schema_version=int(data["schema_version"]),
            snapshot=ProcStoreSnapshot.from_dict(data["snapshot"]),
            pruned_proc_ids=pruned_proc_ids,
            pruned_log_proc_ids=[
                str(item) for item in data.get("pruned_log_proc_ids") or pruned_proc_ids
            ],
        )


__all__ = [
    "ProcLogRetentionEntry",
    "ProcLogRetentionResult",
    "ProcPruneOutcome",
    "ProcPrunedStateRetention",
]

"""Proc-store snapshot records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.core.wire import known_field_kwargs

from .common import require_wire_schema
from .proc import Proc


@dataclass(frozen=True)
class ProcStoreStats:
    """Parse statistics returned with a proc-store snapshot."""

    total_lines: int = 0
    blank_lines: int = 0
    invalid_json_lines: int = 0
    invalid_record_lines: int = 0
    loaded_rows: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcStoreStats:
        return cls(
            **{
                name: int(value)
                for name, value in known_field_kwargs(cls, data).items()
            }
        )


@dataclass(frozen=True)
class ProcStoreSnapshot:
    """Newest-first proc rows plus store parse statistics."""

    schema_version: int
    procs: list[Proc] = field(default_factory=list)
    stats: ProcStoreStats = field(default_factory=ProcStoreStats)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcStoreSnapshot:
        require_wire_schema(data)
        raw_procs = data.get("procs")
        if raw_procs is None:
            raw_procs = data.get("tasks")
        return cls(
            schema_version=int(data["schema_version"]),
            procs=[Proc.from_dict(item) for item in raw_procs or []],
            stats=ProcStoreStats.from_dict(data.get("stats") or {}),
        )


@dataclass(frozen=True)
class ProcAppendOutcome:
    schema_version: int
    snapshot: ProcStoreSnapshot
    pruned_proc_ids: list[str] = field(default_factory=list)
    pruned_log_proc_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcAppendOutcome:
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
    "ProcAppendOutcome",
    "ProcStoreSnapshot",
    "ProcStoreStats",
]

"""Typed Python records for the Rust proc wire."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from sase.core.wire import known_field_kwargs

PROC_WIRE_SCHEMA_VERSION: Final = 2
SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS: Final = frozenset({1, PROC_WIRE_SCHEMA_VERSION})

ACTIVE_PROC_STATUSES: Final = frozenset({"pending", "running"})
TERMINAL_PROC_STATUSES: Final = frozenset({"success", "error", "killed"})

# A supervised proc submitted by a session, attributed to it.
COMMAND_PROC_KIND: Final = "command"
# A proc a TUI process runs itself and mirrors into the store.
TUI_PROC_KIND: Final = "tui"
# A supervised proc no session owns, so every surface always shows it.
DETACHED_PROC_KIND: Final = "detached"
PROC_KINDS: Final = frozenset({COMMAND_PROC_KIND, TUI_PROC_KIND, DETACHED_PROC_KIND})


@dataclass(frozen=True)
class Proc:
    """One durable background proc."""

    proc_id: str
    label: str
    kind: str
    status: str
    command: list[str]
    cwd: str
    origin: str
    created_at: str
    log_path: str
    project: str | None = None
    workspace_num: int | None = None
    session_id: str | None = None
    session_label: str | None = None
    cl_name: str | None = None
    tags: list[str] = field(default_factory=list)
    pid: int | None = None
    pgid: int | None = None
    exit_code: int | None = None
    phase: str | None = None
    message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Proc:
        """Rehydrate a proc while ignoring additive wire fields."""
        values = known_field_kwargs(cls, data)
        values["proc_id"] = str(
            data["proc_id"] if "proc_id" in data else data["task_id"]
        )
        values["label"] = str(data["label"])
        values["kind"] = str(data["kind"])
        values["status"] = str(data["status"])
        values["command"] = [str(item) for item in data.get("command") or []]
        values["cwd"] = str(data["cwd"])
        values["origin"] = str(data["origin"])
        values["created_at"] = str(data["created_at"])
        values["log_path"] = str(data["log_path"])
        values["tags"] = [str(item) for item in data.get("tags") or []]
        for name in (
            "project",
            "session_id",
            "session_label",
            "cl_name",
            "phase",
            "message",
            "started_at",
            "finished_at",
        ):
            values[name] = None if data.get(name) is None else str(data[name])
        for name in ("workspace_num", "pid", "pgid", "exit_code"):
            values[name] = None if data.get(name) is None else int(data[name])
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return the complete dict shape accepted by ``sase_core_rs``."""
        return {
            name: getattr(self, name)
            for name in (
                "proc_id",
                "label",
                "kind",
                "status",
                "command",
                "cwd",
                "project",
                "workspace_num",
                "session_id",
                "session_label",
                "origin",
                "cl_name",
                "tags",
                "pid",
                "pgid",
                "exit_code",
                "phase",
                "message",
                "created_at",
                "started_at",
                "finished_at",
                "log_path",
            )
        }


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
        _require_schema(data)
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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcAppendOutcome:
        _require_schema(data)
        return cls(
            schema_version=int(data["schema_version"]),
            snapshot=ProcStoreSnapshot.from_dict(data["snapshot"]),
            pruned_proc_ids=[
                str(item)
                for item in (
                    data.get("pruned_proc_ids")
                    if data.get("pruned_proc_ids") is not None
                    else data.get("pruned_task_ids")
                )
                or []
            ],
        )


@dataclass(frozen=True)
class _Unset:
    pass


UNSET: Final = _Unset()
UpdateValue = str | int | list[str] | None | _Unset


@dataclass(frozen=True)
class ProcUpdate:
    """Partial proc mutation; ``UNSET`` differs from an explicit ``None``."""

    proc_id: str
    label: UpdateValue = UNSET
    kind: UpdateValue = UNSET
    status: UpdateValue = UNSET
    command: UpdateValue = UNSET
    cwd: UpdateValue = UNSET
    project: UpdateValue = UNSET
    workspace_num: UpdateValue = UNSET
    session_id: UpdateValue = UNSET
    session_label: UpdateValue = UNSET
    origin: UpdateValue = UNSET
    cl_name: UpdateValue = UNSET
    tags: UpdateValue = UNSET
    pid: UpdateValue = UNSET
    pgid: UpdateValue = UNSET
    exit_code: UpdateValue = UNSET
    phase: UpdateValue = UNSET
    message: UpdateValue = UNSET
    created_at: UpdateValue = UNSET
    started_at: UpdateValue = UNSET
    finished_at: UpdateValue = UNSET
    log_path: UpdateValue = UNSET

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcUpdate:
        return cls(**known_field_kwargs(cls, data))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"proc_id": self.proc_id}
        for name in self.__dataclass_fields__:
            if name == "proc_id":
                continue
            value = getattr(self, name)
            if value is not UNSET:
                payload[name] = value
        return payload


@dataclass(frozen=True)
class ProcUpdateOutcome:
    schema_version: int
    proc: Proc | None
    matched: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcUpdateOutcome:
        _require_schema(data)
        raw_proc = data.get("proc") if "proc" in data else data.get("task")
        return cls(
            schema_version=int(data["schema_version"]),
            proc=(Proc.from_dict(raw_proc) if isinstance(raw_proc, Mapping) else None),
            matched=bool(data.get("matched", False)),
        )


@dataclass(frozen=True)
class ProcPruneOutcome:
    schema_version: int
    snapshot: ProcStoreSnapshot
    pruned_proc_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcPruneOutcome:
        _require_schema(data)
        return cls(
            schema_version=int(data["schema_version"]),
            snapshot=ProcStoreSnapshot.from_dict(data["snapshot"]),
            pruned_proc_ids=[
                str(item)
                for item in (
                    data.get("pruned_proc_ids")
                    if data.get("pruned_proc_ids") is not None
                    else data.get("pruned_task_ids")
                )
                or []
            ],
        )


def _require_schema(data: Mapping[str, Any]) -> None:
    schema = int(data["schema_version"])
    if schema not in SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS:
        raise ValueError(
            f"proc wire schema mismatch: got {schema}, "
            f"expected one of {sorted(SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS)}"
        )


__all__ = [
    "ACTIVE_PROC_STATUSES",
    "COMMAND_PROC_KIND",
    "DETACHED_PROC_KIND",
    "PROC_KINDS",
    "PROC_WIRE_SCHEMA_VERSION",
    "SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS",
    "TERMINAL_PROC_STATUSES",
    "TUI_PROC_KIND",
    "UNSET",
    "Proc",
    "ProcAppendOutcome",
    "ProcPruneOutcome",
    "ProcStoreSnapshot",
    "ProcStoreStats",
    "ProcUpdate",
    "ProcUpdateOutcome",
]

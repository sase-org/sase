"""Typed Python records for the Rust background-task wire."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from sase.core.wire import known_field_kwargs

TASK_WIRE_SCHEMA_VERSION: Final = 1

ACTIVE_TASK_STATUSES: Final = frozenset({"pending", "running"})
TERMINAL_TASK_STATUSES: Final = frozenset({"success", "error", "killed"})

# A supervised task submitted by a session, attributed to it.
COMMAND_TASK_KIND: Final = "command"
# A task a TUI process runs itself and mirrors into the store.
TUI_TASK_KIND: Final = "tui"
# A supervised task no session owns, so every surface always shows it.
DETACHED_TASK_KIND: Final = "detached"
TASK_KINDS: Final = frozenset({COMMAND_TASK_KIND, TUI_TASK_KIND, DETACHED_TASK_KIND})


@dataclass(frozen=True)
class BackgroundTask:
    """One durable background task."""

    task_id: str
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
    def from_dict(cls, data: Mapping[str, Any]) -> BackgroundTask:
        """Rehydrate a task while ignoring additive wire fields."""
        values = known_field_kwargs(cls, data)
        values["task_id"] = str(data["task_id"])
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
                "task_id",
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
class TaskStoreStats:
    """Parse statistics returned with a task-store snapshot."""

    total_lines: int = 0
    blank_lines: int = 0
    invalid_json_lines: int = 0
    invalid_record_lines: int = 0
    loaded_rows: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskStoreStats:
        return cls(
            **{
                name: int(value)
                for name, value in known_field_kwargs(cls, data).items()
            }
        )


@dataclass(frozen=True)
class TaskStoreSnapshot:
    """Newest-first task rows plus store parse statistics."""

    schema_version: int
    tasks: list[BackgroundTask] = field(default_factory=list)
    stats: TaskStoreStats = field(default_factory=TaskStoreStats)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskStoreSnapshot:
        _require_schema(data)
        return cls(
            schema_version=int(data["schema_version"]),
            tasks=[BackgroundTask.from_dict(item) for item in data.get("tasks") or []],
            stats=TaskStoreStats.from_dict(data.get("stats") or {}),
        )


@dataclass(frozen=True)
class TaskAppendOutcome:
    schema_version: int
    snapshot: TaskStoreSnapshot
    pruned_task_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskAppendOutcome:
        _require_schema(data)
        return cls(
            schema_version=int(data["schema_version"]),
            snapshot=TaskStoreSnapshot.from_dict(data["snapshot"]),
            pruned_task_ids=[str(item) for item in data.get("pruned_task_ids") or []],
        )


@dataclass(frozen=True)
class _Unset:
    pass


UNSET: Final = _Unset()
UpdateValue = str | int | list[str] | None | _Unset


@dataclass(frozen=True)
class TaskUpdate:
    """Partial task mutation; ``UNSET`` differs from an explicit ``None``."""

    task_id: str
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
    def from_dict(cls, data: Mapping[str, Any]) -> TaskUpdate:
        return cls(**known_field_kwargs(cls, data))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"task_id": self.task_id}
        for name in self.__dataclass_fields__:
            if name == "task_id":
                continue
            value = getattr(self, name)
            if value is not UNSET:
                payload[name] = value
        return payload


@dataclass(frozen=True)
class TaskUpdateOutcome:
    schema_version: int
    task: BackgroundTask | None
    matched: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskUpdateOutcome:
        _require_schema(data)
        raw_task = data.get("task")
        return cls(
            schema_version=int(data["schema_version"]),
            task=(
                BackgroundTask.from_dict(raw_task)
                if isinstance(raw_task, Mapping)
                else None
            ),
            matched=bool(data.get("matched", False)),
        )


@dataclass(frozen=True)
class TaskPruneOutcome:
    schema_version: int
    snapshot: TaskStoreSnapshot
    pruned_task_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskPruneOutcome:
        _require_schema(data)
        return cls(
            schema_version=int(data["schema_version"]),
            snapshot=TaskStoreSnapshot.from_dict(data["snapshot"]),
            pruned_task_ids=[str(item) for item in data.get("pruned_task_ids") or []],
        )


def _require_schema(data: Mapping[str, Any]) -> None:
    schema = int(data["schema_version"])
    if schema != TASK_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"task wire schema mismatch: got {schema}, "
            f"expected {TASK_WIRE_SCHEMA_VERSION}"
        )


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "COMMAND_TASK_KIND",
    "DETACHED_TASK_KIND",
    "TASK_KINDS",
    "TASK_WIRE_SCHEMA_VERSION",
    "TERMINAL_TASK_STATUSES",
    "TUI_TASK_KIND",
    "UNSET",
    "BackgroundTask",
    "TaskAppendOutcome",
    "TaskPruneOutcome",
    "TaskStoreSnapshot",
    "TaskStoreStats",
    "TaskUpdate",
    "TaskUpdateOutcome",
]

"""Typed Python records for the Rust proc wire."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from sase.core.wire import known_field_kwargs

PROC_WIRE_SCHEMA_VERSION: Final = 3
SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS: Final = frozenset({1, 2, PROC_WIRE_SCHEMA_VERSION})

ACTIVE_PROC_STATUSES: Final = frozenset({"pending", "running", "settling"})
TERMINAL_PROC_STATUSES: Final = frozenset({"success", "error", "killed"})

# A supervised proc submitted by a session, attributed to it.
COMMAND_PROC_KIND: Final = "command"
# A proc a TUI process runs itself and mirrors into the store.
TUI_PROC_KIND: Final = "tui"
# A supervised proc no session owns, so every surface always shows it.
DETACHED_PROC_KIND: Final = "detached"
PROC_KINDS: Final = frozenset({COMMAND_PROC_KIND, TUI_PROC_KIND, DETACHED_PROC_KIND})
PROC_LIFECYCLE_LEGACY: Final = "legacy"
PROC_LIFECYCLE_PROC_SHELL: Final = "proc-shell"
STORE_LOG_OWNER: Final = "proc-store"
ARTIFACTS_LOG_OWNER: Final = "artifacts"
XPROMPT_PROC_ORIGIN: Final = "xprompt-proc"


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
    schema_version: int = PROC_WIRE_SCHEMA_VERSION
    lifecycle: str = PROC_LIFECYCLE_LEGACY
    argv: list[str] = field(default_factory=list)
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
    log_owner: str = STORE_LOG_OWNER
    shell_name: str | None = None
    shell_kind: str | None = None
    concurrency_keys: list[str] = field(default_factory=list)
    request_fingerprint: str | None = None
    reserved_by: str | None = None
    reserved_at: str | None = None
    supervisor_id: str | None = None
    supervisor_claimed_at: str | None = None
    stop_requested_by: str | None = None
    stop_requested_at: str | None = None
    stop_reason: str | None = None
    timeout_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    settling_started_at: str | None = None
    settled_by: str | None = None
    settled_at: str | None = None
    finished_by: str | None = None
    result: Any | None = None
    xprompt_proc: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.argv and self.command:
            object.__setattr__(self, "argv", list(self.command))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Proc:
        """Rehydrate a proc while ignoring additive wire fields."""
        values = known_field_kwargs(cls, data)
        values["schema_version"] = int(data.get("schema_version", 2))
        values["proc_id"] = str(
            data["proc_id"] if "proc_id" in data else data["task_id"]
        )
        values["label"] = str(data["label"])
        values["kind"] = str(data["kind"])
        values["status"] = str(data["status"])
        command = [str(item) for item in data.get("command") or []]
        argv = [str(item) for item in data.get("argv") or command]
        if not command and argv:
            command = list(argv)
        values["command"] = command
        values["argv"] = argv
        values["cwd"] = str(data["cwd"])
        values["origin"] = str(data["origin"])
        values["created_at"] = str(data["created_at"])
        values["log_path"] = str(data["log_path"])
        values["lifecycle"] = str(data.get("lifecycle") or PROC_LIFECYCLE_LEGACY)
        values["log_owner"] = str(data.get("log_owner") or STORE_LOG_OWNER)
        values["tags"] = [str(item) for item in data.get("tags") or []]
        values["concurrency_keys"] = [
            str(item) for item in data.get("concurrency_keys") or []
        ]
        for name in (
            "project",
            "session_id",
            "session_label",
            "cl_name",
            "phase",
            "message",
            "started_at",
            "finished_at",
            "shell_name",
            "shell_kind",
            "request_fingerprint",
            "reserved_by",
            "reserved_at",
            "supervisor_id",
            "supervisor_claimed_at",
            "stop_requested_by",
            "stop_requested_at",
            "stop_reason",
            "settling_started_at",
            "settled_by",
            "settled_at",
            "finished_by",
        ):
            values[name] = None if data.get(name) is None else str(data[name])
        for name in (
            "workspace_num",
            "pid",
            "pgid",
            "exit_code",
            "timeout_seconds",
            "idle_timeout_seconds",
        ):
            values[name] = None if data.get(name) is None else int(data[name])
        values["result"] = data.get("result")
        meta = data.get("xprompt_proc")
        values["xprompt_proc"] = dict(meta) if isinstance(meta, Mapping) else None
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return the complete dict shape accepted by ``sase_core_rs``."""
        return {
            name: getattr(self, name)
            for name in (
                "schema_version",
                "proc_id",
                "label",
                "kind",
                "status",
                "lifecycle",
                "argv",
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
                "log_owner",
                "shell_name",
                "shell_kind",
                "concurrency_keys",
                "request_fingerprint",
                "reserved_by",
                "reserved_at",
                "supervisor_id",
                "supervisor_claimed_at",
                "stop_requested_by",
                "stop_requested_at",
                "stop_reason",
                "timeout_seconds",
                "idle_timeout_seconds",
                "settling_started_at",
                "settled_by",
                "settled_at",
                "finished_by",
                "result",
                "xprompt_proc",
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
    pruned_log_proc_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcAppendOutcome:
        _require_schema(data)
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


@dataclass(frozen=True)
class _Unset:
    pass


UNSET: Final = _Unset()
UpdateValue = str | int | list[str] | dict[str, Any] | None | _Unset


@dataclass(frozen=True)
class ProcReserve:
    """Strict proc-shell reservation request."""

    proc_id: str
    label: str
    argv: list[str]
    cwd: str
    created_at: str
    log_path: str
    request_fingerprint: str
    reserved_by: str
    schema_version: int = PROC_WIRE_SCHEMA_VERSION
    kind: str = COMMAND_PROC_KIND
    project: str | None = None
    workspace_num: int | None = None
    session_id: str | None = None
    session_label: str | None = None
    origin: str = "proc-shell"
    cl_name: str | None = None
    tags: list[str] = field(default_factory=list)
    log_owner: str = STORE_LOG_OWNER
    shell_name: str | None = None
    shell_kind: str | None = "proc"
    concurrency_keys: list[str] = field(default_factory=list)
    timeout_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    xprompt_proc: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcReserve:
        values = known_field_kwargs(cls, data)
        values["argv"] = [str(item) for item in data.get("argv") or []]
        values["tags"] = [str(item) for item in data.get("tags") or []]
        values["concurrency_keys"] = [
            str(item) for item in data.get("concurrency_keys") or []
        ]
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ProcReserveOutcome:
    schema_version: int
    proc: Proc
    snapshot: ProcStoreSnapshot
    reserved: bool
    replayed: bool
    pruned_proc_ids: list[str] = field(default_factory=list)
    pruned_log_proc_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcReserveOutcome:
        _require_schema(data)
        return cls(
            schema_version=int(data["schema_version"]),
            proc=Proc.from_dict(data["proc"]),
            snapshot=ProcStoreSnapshot.from_dict(data["snapshot"]),
            reserved=bool(data.get("reserved", False)),
            replayed=bool(data.get("replayed", False)),
            pruned_proc_ids=[str(item) for item in data.get("pruned_proc_ids") or []],
            pruned_log_proc_ids=[
                str(item) for item in data.get("pruned_log_proc_ids") or []
            ],
        )


@dataclass(frozen=True)
class ProcSupervisorClaim:
    proc_id: str
    supervisor_id: str
    claimed_at: str
    pid: int | None = None
    pgid: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcSupervisorClaim:
        return cls(**known_field_kwargs(cls, data))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ProcStopRequest:
    proc_id: str
    requested_by: str
    requested_at: str
    reason: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcStopRequest:
        return cls(**known_field_kwargs(cls, data))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ProcSettlement:
    proc_id: str
    supervisor_id: str
    settling_at: str
    exit_code: int | None = None
    message: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcSettlement:
        return cls(**known_field_kwargs(cls, data))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ProcFinish:
    proc_id: str
    supervisor_id: str
    status: str
    finished_at: str
    exit_code: int | None = None
    message: str | None = None
    result: Any | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcFinish:
        return cls(**known_field_kwargs(cls, data))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ProcUpdate:
    """Partial proc mutation; ``UNSET`` differs from an explicit ``None``."""

    proc_id: str
    schema_version: UpdateValue = UNSET
    label: UpdateValue = UNSET
    kind: UpdateValue = UNSET
    status: UpdateValue = UNSET
    lifecycle: UpdateValue = UNSET
    argv: UpdateValue = UNSET
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
    log_owner: UpdateValue = UNSET
    shell_name: UpdateValue = UNSET
    shell_kind: UpdateValue = UNSET
    concurrency_keys: UpdateValue = UNSET
    request_fingerprint: UpdateValue = UNSET
    reserved_by: UpdateValue = UNSET
    reserved_at: UpdateValue = UNSET
    supervisor_id: UpdateValue = UNSET
    supervisor_claimed_at: UpdateValue = UNSET
    stop_requested_by: UpdateValue = UNSET
    stop_requested_at: UpdateValue = UNSET
    stop_reason: UpdateValue = UNSET
    timeout_seconds: UpdateValue = UNSET
    idle_timeout_seconds: UpdateValue = UNSET
    settling_started_at: UpdateValue = UNSET
    settled_by: UpdateValue = UNSET
    settled_at: UpdateValue = UNSET
    finished_by: UpdateValue = UNSET
    result: UpdateValue = UNSET
    xprompt_proc: UpdateValue = UNSET

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
    pruned_log_proc_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcPruneOutcome:
        _require_schema(data)
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
    "PROC_LIFECYCLE_LEGACY",
    "PROC_LIFECYCLE_PROC_SHELL",
    "PROC_WIRE_SCHEMA_VERSION",
    "STORE_LOG_OWNER",
    "SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS",
    "TERMINAL_PROC_STATUSES",
    "TUI_PROC_KIND",
    "UNSET",
    "Proc",
    "ProcAppendOutcome",
    "ProcFinish",
    "ProcPruneOutcome",
    "ProcReserve",
    "ProcReserveOutcome",
    "ProcSettlement",
    "ProcStopRequest",
    "ProcStoreSnapshot",
    "ProcStoreStats",
    "ProcSupervisorClaim",
    "ProcUpdate",
    "ProcUpdateOutcome",
]

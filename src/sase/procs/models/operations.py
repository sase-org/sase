"""Proc mutation requests and lifecycle outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from sase.core.wire import known_field_kwargs
from sase.procs.service_meta import ProcServiceBlock

from .common import (
    COMMAND_PROC_KIND,
    PROC_WIRE_SCHEMA_VERSION,
    STORE_LOG_OWNER,
    require_wire_schema,
)
from .proc import Proc
from .snapshots import ProcStoreSnapshot


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
    service: ProcServiceBlock | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProcReserve:
        values = known_field_kwargs(cls, data)
        values["argv"] = [str(item) for item in data.get("argv") or []]
        values["tags"] = [str(item) for item in data.get("tags") or []]
        values["concurrency_keys"] = [
            str(item) for item in data.get("concurrency_keys") or []
        ]
        values["service"] = ProcServiceBlock.from_dict(data.get("service"))
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in self.__dataclass_fields__}
        payload["service"] = (
            self.service.to_dict() if self.service is not None else None
        )
        return payload


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
        require_wire_schema(data)
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
        require_wire_schema(data)
        raw_proc = data.get("proc") if "proc" in data else data.get("task")
        return cls(
            schema_version=int(data["schema_version"]),
            proc=(Proc.from_dict(raw_proc) if isinstance(raw_proc, Mapping) else None),
            matched=bool(data.get("matched", False)),
        )


__all__ = [
    "UNSET",
    "ProcFinish",
    "ProcReserve",
    "ProcReserveOutcome",
    "ProcSettlement",
    "ProcStopRequest",
    "ProcSupervisorClaim",
    "ProcUpdate",
    "ProcUpdateOutcome",
]

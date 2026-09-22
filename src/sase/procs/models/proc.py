"""The durable proc record."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.core.wire import known_field_kwargs
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    ProcServiceBlock,
    host_service_tag_name,
)

from .common import PROC_LIFECYCLE_LEGACY, PROC_WIRE_SCHEMA_VERSION, STORE_LOG_OWNER


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
    service: ProcServiceBlock | None = None

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
        if isinstance(meta, Mapping):
            xprompt_proc = dict(meta)
            if data.get("origin") == "xprompt-proc":
                if "label" not in xprompt_proc and data.get("label") is not None:
                    xprompt_proc["label"] = str(data["label"])
                if (
                    "shell_name" not in xprompt_proc
                    and data.get("shell_name") is not None
                ):
                    xprompt_proc["shell_name"] = str(data["shell_name"])
            values["xprompt_proc"] = xprompt_proc
        else:
            values["xprompt_proc"] = None
        values["service"] = ProcServiceBlock.from_dict(data.get("service"))
        return cls(**values)

    @property
    def service_name(self) -> str | None:
        """Return the service proc this row runs, if it names one.

        The wire ``service`` block is authoritative, but it is additive: a
        ``sase_core_rs`` build that predates it drops the block whenever it
        rewrites the store. A host-written daemon row still carries the host
        origin and its ``service:<name>`` tag, so fall back to those.
        """
        if self.service is not None:
            return self.service.name or None
        if self.origin != SERVICE_HOST_ORIGIN:
            return None
        return host_service_tag_name(self.tags)

    @property
    def is_service(self) -> bool:
        return self.service is not None

    def to_dict(self) -> dict[str, Any]:
        """Return the complete dict shape accepted by ``sase_core_rs``."""
        payload = {
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
                "service",
            )
        }
        payload["service"] = (
            self.service.to_dict() if self.service is not None else None
        )
        return payload


__all__ = [
    "Proc",
]

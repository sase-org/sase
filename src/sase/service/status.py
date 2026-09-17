"""Typed facade for the Rust-owned service status snapshot."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from os import PathLike
from pathlib import Path
from typing import Any

from sase.config.inventory import ConfigDiagnostic
from sase.core.rust import require_rust_binding
from sase.service.boot import current_boot_id
from sase.service.config import (
    ServiceConfigComposition,
    ServiceEnablementSource,
    ServiceLauncher,
    ServiceProcConfig,
)
from sase.service.paths import service_status_path
from sase.service.restart import ServiceRestartDecision
from sase.service.state import (
    ServiceEnablementOverride,
    ServiceHostRecord,
    ServiceMarker,
    ServiceState,
    ServiceStateSnapshot,
    ServiceStop,
)

_UNSET: Any = object()


@dataclass(frozen=True)
class ServiceEnablement:
    """Effective enablement plus provenance for one service proc."""

    enabled: bool
    provenance: str
    summary: str
    layer: str | None = None
    path: str | None = None
    updated_at: float | None = None
    _wire: dict[str, Any] = dataclass_field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceEnablement:
        wire = dict(payload)
        return cls(
            enabled=bool(payload["enabled"]),
            provenance=str(payload["provenance"]),
            layer=payload.get("layer"),
            path=payload.get("path"),
            updated_at=(
                None
                if payload.get("updated_at") is None
                else float(payload["updated_at"])
            ),
            summary=str(payload["summary"]),
            _wire=wire,
        )

    def to_wire(self) -> dict[str, Any]:
        if self._wire:
            return dict(self._wire)
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "provenance": self.provenance,
            "summary": self.summary,
        }
        if self.layer is not None:
            payload["layer"] = self.layer
        if self.path is not None:
            payload["path"] = self.path
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at
        return payload


@dataclass(frozen=True)
class ServiceHostObservation:
    """Current host observation used to build a status snapshot."""

    record: ServiceHostRecord | None = None
    lock_held: bool = False
    pid_alive: bool | None = None
    platform_unit: str | None = None
    stale_after_seconds: float = 15.0

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "lock_held": self.lock_held,
            "stale_after_seconds": self.stale_after_seconds,
        }
        if self.record is not None:
            payload["record"] = self.record.to_wire()
        if self.pid_alive is not None:
            payload["pid_alive"] = self.pid_alive
        if self.platform_unit is not None:
            payload["platform_unit"] = self.platform_unit
        return payload


@dataclass(frozen=True)
class ServiceProcLastExit:
    """Last known exit detail for a service proc."""

    exit_code: int | None = None
    signal: int | None = None
    spawn_error: str | None = None
    finished_at: float | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceProcLastExit:
        return cls(
            exit_code=(
                None if payload.get("exit_code") is None else int(payload["exit_code"])
            ),
            signal=None if payload.get("signal") is None else int(payload["signal"]),
            spawn_error=payload.get("spawn_error"),
            finished_at=(
                None
                if payload.get("finished_at") is None
                else float(payload["finished_at"])
            ),
        )

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        if self.signal is not None:
            payload["signal"] = self.signal
        if self.spawn_error is not None:
            payload["spawn_error"] = self.spawn_error
        if self.finished_at is not None:
            payload["finished_at"] = self.finished_at
        return payload


@dataclass(frozen=True)
class ServiceProcReportedStatus:
    """Optional per-proc status.json report surfaced in the snapshot."""

    summary: str
    state: str
    updated_at: float

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceProcReportedStatus:
        return cls(
            summary=str(payload["summary"]),
            state=str(payload["state"]),
            updated_at=float(payload["updated_at"]),
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "state": self.state,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ServiceProcObservation:
    """Current runtime observation for one named service proc."""

    name: str
    pid: int | None = None
    alive: bool = False
    proc_id: str | None = None
    started_at: float | None = None
    last_exit: ServiceProcLastExit | None = None
    restart: ServiceRestartDecision | None = None
    restarts: int = 0
    reported: ServiceProcReportedStatus | None = None
    log_path: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "alive": self.alive,
            "restarts": self.restarts,
        }
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.proc_id is not None:
            payload["proc_id"] = self.proc_id
        if self.started_at is not None:
            payload["started_at"] = self.started_at
        if self.last_exit is not None:
            payload["last_exit"] = self.last_exit.to_wire()
        if self.restart is not None:
            payload["restart"] = _restart_decision_to_wire(self.restart)
        if self.reported is not None:
            payload["reported"] = self.reported.to_wire()
        if self.log_path is not None:
            payload["log_path"] = self.log_path
        return payload


@dataclass(frozen=True)
class ServiceStatusHost:
    """Derived service-host status row."""

    state: str
    summary: str
    pid: int | None = None
    mode: str | None = None
    platform_unit: str | None = None
    started_at: float | None = None
    heartbeat_at: float | None = None
    heartbeat_age_seconds: float | None = None
    sase_version: str | None = None
    error: str | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceStatusHost:
        return cls(
            state=str(payload["state"]),
            pid=None if payload.get("pid") is None else int(payload["pid"]),
            mode=payload.get("mode"),
            platform_unit=payload.get("platform_unit"),
            started_at=(
                None
                if payload.get("started_at") is None
                else float(payload["started_at"])
            ),
            heartbeat_at=(
                None
                if payload.get("heartbeat_at") is None
                else float(payload["heartbeat_at"])
            ),
            heartbeat_age_seconds=(
                None
                if payload.get("heartbeat_age_seconds") is None
                else float(payload["heartbeat_age_seconds"])
            ),
            sase_version=payload.get("sase_version"),
            error=payload.get("error"),
            summary=str(payload["summary"]),
        )

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": self.state,
            "summary": self.summary,
        }
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.mode is not None:
            payload["mode"] = self.mode
        if self.platform_unit is not None:
            payload["platform_unit"] = self.platform_unit
        if self.started_at is not None:
            payload["started_at"] = self.started_at
        if self.heartbeat_at is not None:
            payload["heartbeat_at"] = self.heartbeat_at
        if self.heartbeat_age_seconds is not None:
            payload["heartbeat_age_seconds"] = self.heartbeat_age_seconds
        if self.sase_version is not None:
            payload["sase_version"] = self.sase_version
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class ServiceStatusProc:
    """Derived status row for a configured or orphan service proc."""

    name: str
    source: str
    declared_by: str
    mode: str
    available: bool
    enablement: ServiceEnablement
    desired: str
    state: str
    summary: str
    description: str | None = None
    pid: int | None = None
    proc_id: str | None = None
    started_at: float | None = None
    last_exit: ServiceProcLastExit | None = None
    restart: dict[str, Any] | None = None
    restarts: int = 0
    reported: ServiceProcReportedStatus | None = None
    log_path: str | None = None
    launcher_summary: str | None = None
    unavailable_reason: str | None = None
    stop: ServiceStop | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceStatusProc:
        last_exit = payload.get("last_exit")
        reported = payload.get("reported")
        stop = payload.get("stop")
        return cls(
            name=str(payload["name"]),
            description=payload.get("description"),
            source=str(payload["source"]),
            declared_by=str(payload["declared_by"]),
            mode=str(payload["mode"]),
            available=bool(payload["available"]),
            pid=None if payload.get("pid") is None else int(payload["pid"]),
            proc_id=payload.get("proc_id"),
            started_at=(
                None
                if payload.get("started_at") is None
                else float(payload["started_at"])
            ),
            last_exit=ServiceProcLastExit.from_wire(last_exit) if last_exit else None,
            restart=dict(payload["restart"]) if payload.get("restart") else None,
            restarts=int(payload.get("restarts", 0)),
            reported=(
                ServiceProcReportedStatus.from_wire(reported) if reported else None
            ),
            log_path=payload.get("log_path"),
            launcher_summary=payload.get("launcher_summary"),
            unavailable_reason=payload.get("unavailable_reason"),
            enablement=ServiceEnablement.from_wire(payload["enablement"]),
            stop=ServiceStop.from_wire(stop) if stop else None,
            desired=str(payload["desired"]),
            state=str(payload["state"]),
            summary=str(payload["summary"]),
        )

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "source": self.source,
            "declared_by": self.declared_by,
            "mode": self.mode,
            "available": self.available,
            "restarts": self.restarts,
            "enablement": self.enablement.to_wire(),
            "desired": self.desired,
            "state": self.state,
            "summary": self.summary,
        }
        if self.description is not None:
            payload["description"] = self.description
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.proc_id is not None:
            payload["proc_id"] = self.proc_id
        if self.started_at is not None:
            payload["started_at"] = self.started_at
        if self.last_exit is not None:
            payload["last_exit"] = self.last_exit.to_wire()
        if self.restart is not None:
            payload["restart"] = dict(self.restart)
        if self.reported is not None:
            payload["reported"] = self.reported.to_wire()
        if self.log_path is not None:
            payload["log_path"] = self.log_path
        if self.launcher_summary is not None:
            payload["launcher_summary"] = self.launcher_summary
        if self.unavailable_reason is not None:
            payload["unavailable_reason"] = self.unavailable_reason
        if self.stop is not None:
            payload["stop"] = _stop_to_wire(self.stop)
        return payload


@dataclass(frozen=True)
class ServiceStatusSnapshot:
    """Atomic service status snapshot read model."""

    schema_version: int
    generated_at: float
    change_token: str
    host: ServiceStatusHost
    procs: tuple[ServiceStatusProc, ...]
    orphans: tuple[ServiceStatusProc, ...]
    diagnostics: tuple[str, ...]
    _wire: dict[str, Any] = dataclass_field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceStatusSnapshot:
        wire = dict(payload)
        return cls(
            schema_version=int(payload["schema_version"]),
            generated_at=float(payload["generated_at"]),
            change_token=str(payload["change_token"]),
            host=ServiceStatusHost.from_wire(payload["host"]),
            procs=tuple(ServiceStatusProc.from_wire(item) for item in payload["procs"]),
            orphans=tuple(
                ServiceStatusProc.from_wire(item) for item in payload["orphans"]
            ),
            diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
            _wire=wire,
        )

    def to_wire(self) -> dict[str, Any]:
        if self._wire:
            return dict(self._wire)
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "change_token": self.change_token,
            "host": self.host.to_wire(),
            "procs": [item.to_wire() for item in self.procs],
            "orphans": [item.to_wire() for item in self.orphans],
            "diagnostics": list(self.diagnostics),
        }


def resolve_service_enablement(
    entry: ServiceProcConfig,
    override: ServiceEnablementOverride | None = None,
) -> ServiceEnablement:
    """Resolve a config entry plus optional machine override in Rust."""
    binding = require_rust_binding("service_enablement_resolve")
    payload = binding(
        _service_proc_config_to_wire(entry),
        None if override is None else _enablement_override_to_wire(override),
    )
    return ServiceEnablement.from_wire(payload)


def build_service_status(
    config: ServiceConfigComposition,
    state: ServiceState | ServiceStateSnapshot,
    host: ServiceHostObservation,
    procs: Sequence[ServiceProcObservation] = (),
    *,
    generated_at: float | None = None,
    boot_id: str | None | Any = _UNSET,
) -> ServiceStatusSnapshot:
    """Build a status snapshot from config, state, host, and proc observations."""
    binding = require_rust_binding("service_status_build")
    state_value = state.state if isinstance(state, ServiceStateSnapshot) else state
    payload = binding(
        {
            "generated_at": time.time() if generated_at is None else generated_at,
            "boot_id": _boot_id_arg(boot_id),
            "host": host.to_wire(),
            "config": _service_config_to_wire(config),
            "state": _service_state_to_wire(state_value),
            "procs": [item.to_wire() for item in procs],
        }
    )
    return ServiceStatusSnapshot.from_wire(payload)


def write_service_status(
    snapshot: ServiceStatusSnapshot,
    path: str | PathLike[str] | None = None,
) -> None:
    """Atomically write a service status snapshot."""
    binding = require_rust_binding("service_status_write")
    binding(str(_status_path_arg(path)), snapshot.to_wire())


def read_service_status(
    path: str | PathLike[str] | None = None,
) -> ServiceStatusSnapshot | None:
    """Read the service status snapshot, returning None when absent."""
    binding = require_rust_binding("service_status_read")
    payload = binding(str(_status_path_arg(path)))
    if payload is None:
        return None
    return ServiceStatusSnapshot.from_wire(payload)


def _status_path_arg(path: str | PathLike[str] | None) -> Path:
    return service_status_path() if path is None else Path(path).expanduser()


def _boot_id_arg(value: str | None | Any) -> str | None:
    if value is _UNSET:
        return current_boot_id()
    return value


def _service_config_to_wire(config: ServiceConfigComposition) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "fatal": config.fatal,
        "procs": [_service_proc_config_to_wire(item) for item in config.procs],
        "diagnostics": [_diagnostic_to_wire(item) for item in config.diagnostics],
        "ignored_layers": list(config.ignored_layers),
    }


def _diagnostic_to_wire(diagnostic: ConfigDiagnostic) -> dict[str, Any]:
    return {
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "path": diagnostic.path,
        "layer": diagnostic.layer,
    }


def _service_proc_config_to_wire(entry: ServiceProcConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": entry.name,
        "available": entry.available,
        "unavailable_reasons": list(entry.unavailable_reasons),
        "source": entry.source,
        "declared_by": entry.declared_by,
        "enabled": entry.enabled,
        "enablement": _enablement_source_to_wire(entry.enablement),
        "mode": entry.mode,
        "env": dict(entry.env),
        "restart": entry.restart,
        "success_exit_codes": list(entry.success_exit_codes),
        "stop_signal": entry.stop_signal,
        "stop_timeout_seconds": entry.stop_timeout_seconds,
        "after": list(entry.after),
        "log_max_bytes": entry.log_max_bytes,
        "field_provenance": [
            {
                "field": item.field,
                "layer": item.layer,
                "path": item.path,
            }
            for item in entry.field_provenance
        ],
    }
    if entry.description is not None:
        payload["description"] = entry.description
    if entry.launcher is not None:
        payload["launcher"] = _launcher_to_wire(entry.launcher)
    if entry.cwd is not None:
        payload["cwd"] = entry.cwd
    return payload


def _enablement_source_to_wire(source: ServiceEnablementSource) -> dict[str, Any]:
    payload: dict[str, Any] = {"explicit": source.explicit}
    if source.layer is not None:
        payload["layer"] = source.layer
    if source.layer_kind is not None:
        payload["layer_kind"] = source.layer_kind
    if source.path is not None:
        payload["path"] = source.path
    return payload


def _launcher_to_wire(launcher: ServiceLauncher) -> dict[str, Any]:
    if launcher.kind == "builtin":
        return {"kind": "builtin", "builtin": launcher.builtin}
    return {
        "kind": "command",
        "command": launcher.command,
        "argv": list(launcher.argv),
    }


def _service_state_to_wire(state: ServiceState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": state.schema_version,
        "enablement": {
            name: _enablement_override_to_wire(value)
            for name, value in state.enablement.items()
        },
        "stops": {name: _stop_to_wire(value) for name, value in state.stops.items()},
        "markers": {
            name: _marker_to_wire(value) for name, value in state.markers.items()
        },
        "host": None if state.host is None else state.host.to_wire(),
    }
    return payload


def _enablement_override_to_wire(
    override: ServiceEnablementOverride,
) -> dict[str, Any]:
    return {
        "enabled": override.enabled,
        "updated_at": override.updated_at,
        "updated_by": override.updated_by,
    }


def _stop_to_wire(stop: ServiceStop) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stopped_at": stop.stopped_at,
        "stopped_by": stop.stopped_by,
    }
    if stop.boot_id is not None:
        payload["boot_id"] = stop.boot_id
    if stop.reason is not None:
        payload["reason"] = stop.reason
    return payload


def _marker_to_wire(marker: ServiceMarker) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recorded_at": marker.recorded_at,
        "recorded_by": marker.recorded_by,
    }
    if marker.detail is not None:
        payload["detail"] = marker.detail
    return payload


def _restart_decision_to_wire(decision: ServiceRestartDecision) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": decision.schema_version,
        "action": decision.action,
        "clean_exit": decision.clean_exit,
        "delay_seconds": decision.delay_seconds,
        "reason": decision.reason,
        "crash_loop": decision.crash_loop,
        "notify": decision.notify,
        "history": decision.history.to_wire(),
    }
    if decision.restart_at is not None:
        payload["restart_at"] = decision.restart_at
    return payload


__all__ = [
    "ServiceEnablement",
    "ServiceHostObservation",
    "ServiceProcLastExit",
    "ServiceProcObservation",
    "ServiceProcReportedStatus",
    "ServiceStatusHost",
    "ServiceStatusProc",
    "ServiceStatusSnapshot",
    "build_service_status",
    "read_service_status",
    "resolve_service_enablement",
    "write_service_status",
]

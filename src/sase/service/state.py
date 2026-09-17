"""Typed facade for the Rust-owned service state store."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from os import PathLike
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home as _sase_home
from sase.core.rust import require_rust_binding
from sase.service.boot import current_boot_id

_UNSET: Any = object()


@dataclass(frozen=True)
class ServiceEnablementOverride:
    """Machine-local enable/disable override for one service proc."""

    enabled: bool
    updated_at: float
    updated_by: str

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceEnablementOverride:
        return cls(
            enabled=bool(payload["enabled"]),
            updated_at=float(payload["updated_at"]),
            updated_by=str(payload["updated_by"]),
        )


@dataclass(frozen=True)
class ServiceStop:
    """Boot-scoped runtime stop override for one service proc."""

    boot_id: str | None
    stopped_at: float
    stopped_by: str
    reason: str | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceStop:
        return cls(
            boot_id=payload.get("boot_id"),
            stopped_at=float(payload["stopped_at"]),
            stopped_by=str(payload["stopped_by"]),
            reason=payload.get("reason"),
        )


@dataclass(frozen=True)
class ServiceMarker:
    """Small service-host coordination marker."""

    recorded_at: float
    recorded_by: str
    detail: str | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceMarker:
        return cls(
            recorded_at=float(payload["recorded_at"]),
            recorded_by=str(payload["recorded_by"]),
            detail=payload.get("detail"),
        )


@dataclass(frozen=True)
class ServiceHostRecord:
    """Latest service-host heartbeat record."""

    pid: int
    started_at: float
    heartbeat_at: float
    mode: str
    boot_id: str | None = None
    unit: str | None = None
    sase_version: str | None = None
    error: str | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceHostRecord:
        return cls(
            pid=int(payload["pid"]),
            boot_id=payload.get("boot_id"),
            started_at=float(payload["started_at"]),
            heartbeat_at=float(payload["heartbeat_at"]),
            mode=str(payload["mode"]),
            unit=payload.get("unit"),
            sase_version=payload.get("sase_version"),
            error=payload.get("error"),
        )

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pid": self.pid,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "mode": self.mode,
        }
        if self.boot_id is not None:
            payload["boot_id"] = self.boot_id
        if self.unit is not None:
            payload["unit"] = self.unit
        if self.sase_version is not None:
            payload["sase_version"] = self.sase_version
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class ServiceState:
    """Machine-local mutable service state."""

    schema_version: int
    enablement: dict[str, ServiceEnablementOverride] = dataclass_field(
        default_factory=dict
    )
    stops: dict[str, ServiceStop] = dataclass_field(default_factory=dict)
    markers: dict[str, ServiceMarker] = dataclass_field(default_factory=dict)
    host: ServiceHostRecord | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceState:
        host = payload.get("host")
        return cls(
            schema_version=int(payload["schema_version"]),
            enablement={
                str(name): ServiceEnablementOverride.from_wire(value)
                for name, value in payload.get("enablement", {}).items()
            },
            stops={
                str(name): ServiceStop.from_wire(value)
                for name, value in payload.get("stops", {}).items()
            },
            markers={
                str(name): ServiceMarker.from_wire(value)
                for name, value in payload.get("markers", {}).items()
            },
            host=ServiceHostRecord.from_wire(host) if host else None,
        )


@dataclass(frozen=True)
class ServiceStateSnapshot:
    """Read model returned by the locked state store."""

    schema_version: int
    state: ServiceState
    expired_stops: tuple[str, ...]
    read_only: bool
    diagnostics: tuple[str, ...]

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceStateSnapshot:
        return cls(
            schema_version=int(payload["schema_version"]),
            state=ServiceState.from_wire(payload["state"]),
            expired_stops=tuple(str(item) for item in payload.get("expired_stops", ())),
            read_only=bool(payload["read_only"]),
            diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
        )


@dataclass(frozen=True)
class ServiceStateMutationOutcome:
    """Result of one locked service-state mutation."""

    snapshot: ServiceStateSnapshot
    changed: bool

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> ServiceStateMutationOutcome:
        return cls(
            snapshot=ServiceStateSnapshot.from_wire(payload["snapshot"]),
            changed=bool(payload["changed"]),
        )


def read_service_state(
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
) -> ServiceStateSnapshot:
    """Read the locked service state snapshot."""
    binding = require_rust_binding("service_state_read")
    payload = binding(_home_arg(sase_home), _boot_id_arg(boot_id))
    return ServiceStateSnapshot.from_wire(payload)


def set_service_enablement(
    name: str,
    enabled: bool,
    actor: str,
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Set this machine's persistent enablement override for *name*."""
    return _mutate(
        {"op": "set_enablement", "name": name, "enabled": enabled, "actor": actor},
        sase_home=sase_home,
        boot_id=boot_id,
        now=now,
    )


def clear_service_enablement(
    name: str,
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Clear this machine's enablement override for *name*."""
    return _mutate(
        {"op": "clear_enablement", "name": name},
        sase_home=sase_home,
        boot_id=boot_id,
        now=now,
    )


def record_service_stop(
    name: str,
    actor: str,
    *,
    reason: str | None = None,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Record a boot-scoped runtime stop for *name*."""
    mutation: dict[str, Any] = {"op": "stop", "name": name, "actor": actor}
    if reason is not None:
        mutation["reason"] = reason
    return _mutate(mutation, sase_home=sase_home, boot_id=boot_id, now=now)


def clear_service_stop(
    name: str,
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Clear any runtime stop for *name*."""
    return _mutate(
        {"op": "clear_stop", "name": name},
        sase_home=sase_home,
        boot_id=boot_id,
        now=now,
    )


def set_service_marker(
    key: str,
    actor: str,
    *,
    detail: str | None = None,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Set a machine-local service coordination marker."""
    mutation: dict[str, Any] = {"op": "set_marker", "key": key, "actor": actor}
    if detail is not None:
        mutation["detail"] = detail
    return _mutate(mutation, sase_home=sase_home, boot_id=boot_id, now=now)


def clear_service_marker(
    key: str,
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Clear a machine-local service coordination marker."""
    return _mutate(
        {"op": "clear_marker", "key": key},
        sase_home=sase_home,
        boot_id=boot_id,
        now=now,
    )


def record_service_host(
    host: ServiceHostRecord,
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Record the latest service-host heartbeat."""
    return _mutate(
        {"op": "record_host", "host": host.to_wire()},
        sase_home=sase_home,
        boot_id=boot_id,
        now=now,
    )


def clear_service_host(
    pid: int,
    *,
    sase_home: str | PathLike[str] | None = None,
    boot_id: str | None | Any = _UNSET,
    now: float | None = None,
) -> ServiceStateMutationOutcome:
    """Clear the service-host record only when its PID matches *pid*."""
    return _mutate(
        {"op": "clear_host", "pid": pid},
        sase_home=sase_home,
        boot_id=boot_id,
        now=now,
    )


def _mutate(
    mutation: dict[str, Any],
    *,
    sase_home: str | PathLike[str] | None,
    boot_id: str | None | Any,
    now: float | None,
) -> ServiceStateMutationOutcome:
    binding = require_rust_binding("service_state_mutate")
    payload = binding(
        _home_arg(sase_home),
        mutation,
        _boot_id_arg(boot_id),
        time.time() if now is None else now,
    )
    return ServiceStateMutationOutcome.from_wire(payload)


def _home_arg(value: str | PathLike[str] | None) -> str:
    return str(_sase_home() if value is None else Path(value).expanduser())


def _boot_id_arg(value: str | None | Any) -> str | None:
    if value is _UNSET:
        return current_boot_id()
    return value


__all__ = [
    "ServiceEnablementOverride",
    "ServiceHostRecord",
    "ServiceMarker",
    "ServiceState",
    "ServiceStateMutationOutcome",
    "ServiceStateSnapshot",
    "ServiceStop",
    "clear_service_enablement",
    "clear_service_host",
    "clear_service_marker",
    "clear_service_stop",
    "read_service_state",
    "record_service_host",
    "record_service_stop",
    "set_service_enablement",
    "set_service_marker",
]

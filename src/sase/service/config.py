"""Typed Python facade for Rust-owned `service.procs` config composition.

Python discovers config layers and hands them to sase-core's
`service_config_compose` binding; the Rust core owns field-by-field merge,
per-field provenance, and entry availability. Nothing here reimplements that
logic.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sase.config.core import ConfigLayer, current_config_token, load_config_layers
from sase.config.inventory import (
    ConfigBackendError,
    ConfigDiagnostic,
    serialize_config_layer,
)
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ServiceLauncher:
    """A resolved launch target: either a shell/argv command or a builtin."""

    kind: str
    command: Any = None
    argv: tuple[str, ...] = ()
    builtin: str | None = None

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ServiceLauncher:
        if payload["kind"] == "builtin":
            return cls(kind="builtin", builtin=str(payload["builtin"]))
        return cls(
            kind="command",
            command=payload["command"],
            argv=tuple(str(item) for item in payload["argv"]),
        )


@dataclass(frozen=True)
class ServiceEnablementSource:
    """The layer (if any) that supplied the effective `enabled` value."""

    explicit: bool
    layer: str | None = None
    layer_kind: str | None = None
    path: str | None = None

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ServiceEnablementSource:
        return cls(
            explicit=bool(payload["explicit"]),
            layer=payload.get("layer"),
            layer_kind=payload.get("layer_kind"),
            path=payload.get("path"),
        )


@dataclass(frozen=True)
class ServiceFieldProvenance:
    """One layer's contribution to a single `service.procs.<name>` field."""

    field: str
    layer: str
    path: str | None = None

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ServiceFieldProvenance:
        return cls(
            field=str(payload["field"]),
            layer=str(payload["layer"]),
            path=payload.get("path"),
        )


@dataclass(frozen=True)
class ServiceProcConfig:
    """One effective `service.procs.<name>` entry."""

    name: str
    available: bool
    source: str
    declared_by: str
    enabled: bool
    enablement: ServiceEnablementSource
    mode: str
    restart: str
    stop_signal: str
    stop_timeout_seconds: float
    log_max_bytes: int
    description: str | None = None
    unavailable_reasons: tuple[str, ...] = ()
    launcher: ServiceLauncher | None = None
    cwd: str | None = None
    env: dict[str, str] = dataclass_field(default_factory=dict)
    success_exit_codes: tuple[int, ...] = ()
    after: tuple[str, ...] = ()
    field_provenance: tuple[ServiceFieldProvenance, ...] = ()

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ServiceProcConfig:
        launcher = payload.get("launcher")
        return cls(
            name=str(payload["name"]),
            description=payload.get("description"),
            available=bool(payload["available"]),
            unavailable_reasons=tuple(
                str(item) for item in payload.get("unavailable_reasons", ())
            ),
            source=str(payload["source"]),
            declared_by=str(payload["declared_by"]),
            enabled=bool(payload["enabled"]),
            enablement=ServiceEnablementSource.from_wire(payload["enablement"]),
            mode=str(payload["mode"]),
            launcher=ServiceLauncher.from_wire(launcher) if launcher else None,
            cwd=payload.get("cwd"),
            env=dict(payload.get("env", {})),
            restart=str(payload["restart"]),
            success_exit_codes=tuple(
                int(item) for item in payload.get("success_exit_codes", ())
            ),
            stop_signal=str(payload["stop_signal"]),
            stop_timeout_seconds=float(payload["stop_timeout_seconds"]),
            after=tuple(str(item) for item in payload.get("after", ())),
            log_max_bytes=int(payload["log_max_bytes"]),
            field_provenance=tuple(
                ServiceFieldProvenance.from_wire(item)
                for item in payload.get("field_provenance", ())
            ),
        )


@dataclass(frozen=True)
class ServiceConfigComposition:
    """Effective `service.procs` entries plus diagnostics and skipped layers."""

    schema_version: int
    fatal: bool
    procs: tuple[ServiceProcConfig, ...]
    diagnostics: tuple[ConfigDiagnostic, ...]
    ignored_layers: tuple[str, ...]
    layer_inputs: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_wire(
        cls,
        payload: dict[str, Any],
        *,
        layer_inputs: Sequence[dict[str, Any]] = (),
    ) -> ServiceConfigComposition:
        return cls(
            schema_version=int(payload["schema_version"]),
            fatal=bool(payload["fatal"]),
            procs=tuple(ServiceProcConfig.from_wire(item) for item in payload["procs"]),
            diagnostics=tuple(
                ConfigDiagnostic.from_wire(item) for item in payload["diagnostics"]
            ),
            ignored_layers=tuple(
                str(item) for item in payload.get("ignored_layers", ())
            ),
            layer_inputs=tuple(layer_inputs),
        )

    def get(self, name: str) -> ServiceProcConfig | None:
        """Return the effective entry named *name*, if configured."""
        return next((entry for entry in self.procs if entry.name == name), None)


class ServiceConfigError(Exception):
    """Raised when the effective `service.procs` config is invalid."""

    def __init__(self, diagnostics: Sequence[ConfigDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        details = "\n".join(
            f"- {item.severity}: {item.message} ({item.path or 'service'})"
            for item in self.diagnostics
        )
        super().__init__(f"Invalid service configuration:\n{details}")


def compose_service_config(
    layers: Sequence[ConfigLayer] | None = None,
) -> ServiceConfigComposition:
    """Compose the ordered `service.procs` layer stack in Rust."""
    discovered = list(load_config_layers() if layers is None else layers)
    layer_inputs = [serialize_config_layer(layer) for layer in discovered]
    binding = require_rust_binding("service_config_compose")
    try:
        payload = binding({"layers": layer_inputs})
    except ValueError as exc:
        raise ConfigBackendError(str(exc)) from exc
    return ServiceConfigComposition.from_wire(payload, layer_inputs=layer_inputs)


_service_config_cache_lock = threading.RLock()
_service_config_cache_token: tuple[Any, ...] | None = None
_service_config_cache_value: ServiceConfigComposition | None = None


def load_service_config() -> ServiceConfigComposition:
    """Load and fail-closed validate the effective `service.procs` config.

    Raises:
        ServiceConfigError: when the composition reports a section-level
            (`fatal`) diagnostic. A per-entry problem instead leaves that
            entry `available=False` and does not raise.
    """
    global _service_config_cache_token, _service_config_cache_value

    layers = load_config_layers()
    layer_inputs = [serialize_config_layer(layer) for layer in layers]
    token = (*current_config_token(), json.dumps(layer_inputs, sort_keys=True))
    with _service_config_cache_lock:
        if (
            _service_config_cache_token == token
            and _service_config_cache_value is not None
        ):
            composition = _service_config_cache_value
        else:
            composition = compose_service_config(layers)
            _service_config_cache_token = token
            _service_config_cache_value = composition

    if composition.fatal:
        raise ServiceConfigError(composition.diagnostics)
    return composition


__all__ = [
    "ServiceConfigComposition",
    "ServiceConfigError",
    "ServiceEnablementSource",
    "ServiceFieldProvenance",
    "ServiceLauncher",
    "ServiceProcConfig",
    "compose_service_config",
    "load_service_config",
]

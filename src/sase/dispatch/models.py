"""Typed models for configured remote machine dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any, Literal

DISPATCH_SCHEMA_VERSION = 1
FLEET_PROTOCOL_VERSION = 1
FLEET_API_BASE_PATH = "/api/fleet/v1"
FLEET_INSTALLATION_ID_PREFIX = "sase_inst_v1_"

DiagnosticSeverity = Literal["info", "warning", "error"]
MachineState = Literal["ok", "error", "quarantined", "skipped"]

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_INSTALLATION_ID_RE = re.compile(r"^sase_inst_v1_[0-9a-f]{64}$")


class DispatchError(RuntimeError):
    """Base class for dispatch enrollment and registry failures."""


class DispatchConfigError(DispatchError):
    """Raised when dispatch config cannot be interpreted safely."""


class DispatchFeatureDisabled(DispatchError):
    """Raised when a remote-dispatch operation is gated off."""


class EnrollmentBundleError(DispatchError):
    """Raised when a pasted enrollment bundle is invalid."""


class MachineRegistryError(DispatchError):
    """Raised when a configured machine operation cannot be completed."""


@dataclass(frozen=True)
class MachineDiagnostic:
    """Non-fatal dispatch config or credential diagnostic."""

    code: str
    message: str
    severity: DiagnosticSeverity = "warning"
    alias: str = ""


@dataclass(frozen=True)
class _TlsSettings:
    """TLS trust settings for a fleet connection plan."""

    mode: str = "system_roots"
    ca_ref: str | None = None
    server_name_ref: str | None = None

    @classmethod
    def from_config(cls, raw: object) -> _TlsSettings:
        if not isinstance(raw, Mapping):
            return cls()
        mode = _string_or_default(raw.get("mode"), "system_roots")
        ca_ref = _optional_string(raw.get("ca_ref"))
        server_name_ref = _optional_string(raw.get("server_name_ref"))
        return cls(mode=mode, ca_ref=ca_ref, server_name_ref=server_name_ref)

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": DISPATCH_SCHEMA_VERSION,
            "mode": self.mode,
            "ca_ref": self.ca_ref,
            "server_name_ref": self.server_name_ref,
        }

    def to_config(self) -> dict[str, object]:
        payload: dict[str, object] = {"mode": self.mode}
        if self.ca_ref is not None:
            payload["ca_ref"] = self.ca_ref
        if self.server_name_ref is not None:
            payload["server_name_ref"] = self.server_name_ref
        return payload


@dataclass(frozen=True)
class ProviderSettings:
    """Configured dispatch provider metadata."""

    ref: str
    enabled: bool = False
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MachineRecord:
    """One viewer-local alias for a remote fleet gateway installation."""

    alias: str
    provider_ref: str
    endpoint: str
    credential_ref: str
    pinned_installation_id: str
    connection_kind: str = "gateway"
    tls: _TlsSettings = field(default_factory=_TlsSettings)
    quarantined: bool = False
    quarantine_reason: str = ""

    @classmethod
    def from_config(
        cls,
        alias: str,
        raw: object,
    ) -> tuple[MachineRecord | None, tuple[MachineDiagnostic, ...]]:
        diagnostics: list[MachineDiagnostic] = []
        if not isinstance(raw, Mapping):
            return None, (
                MachineDiagnostic(
                    code="machine_record_not_mapping",
                    alias=alias,
                    severity="error",
                    message=f"dispatch.machines.{alias} must be a mapping",
                ),
            )

        try:
            validate_machine_alias(alias)
        except ValueError as exc:
            diagnostics.append(
                MachineDiagnostic(
                    code="invalid_machine_alias",
                    alias=alias,
                    severity="error",
                    message=str(exc),
                )
            )

        provider_ref = _string_or_default(
            raw.get("provider_ref", raw.get("provider")),
            "",
        )
        endpoint = _string_or_default(raw.get("endpoint"), "")
        credential_ref = _string_or_default(raw.get("credential_ref"), "")
        pinned = _string_or_default(
            raw.get("pinned_installation_id", raw.get("installation_pin")),
            "",
        )
        connection_kind = _string_or_default(raw.get("connection_kind"), "gateway")
        tls = _TlsSettings.from_config(raw.get("tls"))
        quarantined = bool(raw.get("quarantined", False))
        quarantine_reason = _string_or_default(raw.get("quarantine_reason"), "")

        for field_name, value in (
            ("provider_ref", provider_ref),
            ("endpoint", endpoint),
            ("credential_ref", credential_ref),
            ("pinned_installation_id", pinned),
        ):
            if not value:
                diagnostics.append(
                    MachineDiagnostic(
                        code=f"missing_{field_name}",
                        alias=alias,
                        severity="error",
                        message=f"dispatch.machines.{alias}.{field_name} is required",
                    )
                )

        if provider_ref and not is_reference_id(provider_ref):
            diagnostics.append(
                MachineDiagnostic(
                    code="invalid_provider_ref",
                    alias=alias,
                    severity="error",
                    message=(
                        f"dispatch.machines.{alias}.provider must be an opaque "
                        "provider reference"
                    ),
                )
            )
        if credential_ref and not is_reference_id(credential_ref):
            diagnostics.append(
                MachineDiagnostic(
                    code="invalid_credential_ref",
                    alias=alias,
                    severity="error",
                    message=(
                        f"dispatch.machines.{alias}.credential_ref must be an "
                        "opaque credential reference"
                    ),
                )
            )
        if pinned and not is_installation_id(pinned):
            diagnostics.append(
                MachineDiagnostic(
                    code="invalid_installation_pin",
                    alias=alias,
                    severity="error",
                    message=(
                        f"dispatch.machines.{alias}.installation_pin must be a "
                        "fleet installation ID"
                    ),
                )
            )

        if any(diagnostic.severity == "error" for diagnostic in diagnostics):
            return None, tuple(diagnostics)
        return (
            cls(
                alias=alias,
                provider_ref=provider_ref,
                endpoint=endpoint,
                credential_ref=credential_ref,
                pinned_installation_id=pinned,
                connection_kind=connection_kind,
                tls=tls,
                quarantined=quarantined,
                quarantine_reason=quarantine_reason,
            ),
            tuple(diagnostics),
        )

    def to_config(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.provider_ref,
            "endpoint": self.endpoint,
            "credential_ref": self.credential_ref,
            "installation_pin": self.pinned_installation_id,
            "connection_kind": self.connection_kind,
        }
        if self.tls != _TlsSettings():
            payload["tls"] = self.tls.to_config()
        if self.quarantined:
            payload["quarantined"] = True
            if self.quarantine_reason:
                payload["quarantine_reason"] = self.quarantine_reason
        return payload

    def to_connection_plan(self) -> dict[str, object]:
        return {
            "schema_version": DISPATCH_SCHEMA_VERSION,
            "provider_ref": self.provider_ref,
            "endpoint": self.endpoint,
            "credential_ref": self.credential_ref,
            "pinned_installation_id": self.pinned_installation_id,
            "connection_kind": self.connection_kind,
            "tls": self.tls.to_plan(),
        }


@dataclass(frozen=True)
class DispatchConfig:
    """Pure projection of dispatch-related config."""

    providers: Mapping[str, ProviderSettings]
    machines: tuple[MachineRecord, ...]
    diagnostics: tuple[MachineDiagnostic, ...] = ()
    discovery_enabled_provider_refs: tuple[str, ...] = ()
    request_timeout_seconds: float = 5.0
    status_cache_seconds: float = 60.0

    def machine_by_alias(self) -> dict[str, MachineRecord]:
        return {machine.alias: machine for machine in self.machines}

    def provider_enabled(self, ref: str) -> bool:
        provider = self.providers.get(ref)
        return bool(provider and provider.enabled)


@dataclass(frozen=True)
class DispatchProviderSpec:
    """One discoverable dispatch provider declared by code or a plugin."""

    ref: str
    display_name: str
    supports_discovery: bool = False
    package: str = "sase"
    version: str = ""
    builtin: bool = False
    diagnostics: tuple[MachineDiagnostic, ...] = ()


@dataclass(frozen=True)
class DiscoveryCandidate:
    """One explicit remote-machine discovery candidate."""

    provider_ref: str
    endpoint: str
    display_name: str = ""
    machine_selector: str = ""
    installation_pin: str = ""
    detail: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider_ref}|{self.endpoint}"


@dataclass(frozen=True)
class BootstrapBundle:
    """Pasteable one-time enrollment bundle."""

    bootstrap_id: str
    bootstrap_secret: str
    pinned_installation_id: str
    supported_protocol_versions: tuple[int, ...] = (FLEET_PROTOCOL_VERSION,)
    requested_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnrollmentResult:
    """Successful or quarantined enrollment response."""

    alias: str
    record: MachineRecord | None
    credential_ref: str
    machine_selector: str
    protocol_version: int | None
    installation_id: str
    credential_id: str
    capabilities: Mapping[str, Sequence[str]]
    quarantined: bool = False
    quarantine_reason: str = ""


@dataclass(frozen=True)
class CredentialRecord:
    """Locally stored bearer token and non-secret credential metadata."""

    ref: str
    token: str
    token_type: str
    provider_ref: str
    endpoint: str
    installation_id: str
    credential_id: str = ""
    scopes: tuple[str, ...] = ()
    issued_at_unix: float | None = None
    expires_at_unix: float | None = None

    def metadata(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ref": self.ref,
            "token_type": self.token_type,
            "provider_ref": self.provider_ref,
            "endpoint": self.endpoint,
            "installation_id": self.installation_id,
            "credential_id": self.credential_id,
            "scopes": list(self.scopes),
        }
        if self.issued_at_unix is not None:
            payload["issued_at_unix"] = self.issued_at_unix
        if self.expires_at_unix is not None:
            payload["expires_at_unix"] = self.expires_at_unix
        return payload


@dataclass(frozen=True)
class MachineStatus:
    """Bounded authenticated hello result for one configured machine."""

    alias: str
    state: MachineState
    provider_ref: str
    endpoint: str
    machine_selector: str = ""
    installation_id: str = ""
    protocol_version: int | None = None
    capabilities: Mapping[str, Sequence[str]] = field(default_factory=dict)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def validate_machine_alias(value: str) -> None:
    if not _ALIAS_RE.fullmatch(value):
        raise ValueError(
            "machine alias must start with an ASCII letter or digit and contain "
            "only letters, digits, '.', '_', or '-'"
        )


def is_reference_id(value: str) -> bool:
    return bool(_REFERENCE_RE.fullmatch(value)) and not _looks_secretish(value)


def is_installation_id(value: str) -> bool:
    return bool(_INSTALLATION_ID_RE.fullmatch(value))


def _looks_secretish(value: str) -> bool:
    lowered = value.casefold()
    return any(part in lowered for part in ("secret", "token", "password", "passwd"))


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _string_or_default(value: object, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def coerce_string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


__all__ = [
    "BootstrapBundle",
    "CredentialRecord",
    "DISPATCH_SCHEMA_VERSION",
    "DispatchConfig",
    "DispatchConfigError",
    "DispatchError",
    "DispatchFeatureDisabled",
    "DispatchProviderSpec",
    "DiscoveryCandidate",
    "EnrollmentBundleError",
    "EnrollmentResult",
    "FLEET_API_BASE_PATH",
    "FLEET_INSTALLATION_ID_PREFIX",
    "FLEET_PROTOCOL_VERSION",
    "MachineDiagnostic",
    "MachineRecord",
    "MachineRegistryError",
    "MachineStatus",
    "ProviderSettings",
    "coerce_string_tuple",
    "is_installation_id",
    "is_reference_id",
    "validate_machine_alias",
]

"""Rust-backed subscription-capacity usage store facade."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

from ..provider_disable import is_finite_number, is_provider_id, require_provider_id

PROVIDER_USAGE_OBSERVATION_SCHEMA_VERSION = 1
PROVIDER_USAGE_PUBLIC_SCHEMA_VERSION = 1
PROVIDER_USAGE_STORE_SCHEMA_VERSION = 1
PROVIDER_USAGE_STATE_FILENAME = "llm_provider_usage.json"

DEFAULT_USAGE_CADENCE_SECONDS = 300.0
DEFAULT_USAGE_WARN_PERCENT = 75.0
DEFAULT_USAGE_CRITICAL_PERCENT = 90.0

PROVIDER_USAGE_STORE_WRITE_RECORDED = "recorded"
PROVIDER_USAGE_STORE_WRITE_UNCHANGED = "unchanged"
PROVIDER_USAGE_STORE_WRITE_STALE_WRITER = "stale_writer"
PROVIDER_USAGE_STORE_WRITE_STATUSES = (
    PROVIDER_USAGE_STORE_WRITE_RECORDED,
    PROVIDER_USAGE_STORE_WRITE_UNCHANGED,
    PROVIDER_USAGE_STORE_WRITE_STALE_WRITER,
)

PROVIDER_USAGE_REFRESH_RESERVED = "reserved"
PROVIDER_USAGE_REFRESH_JOINED = "joined"
PROVIDER_USAGE_REFRESH_STATUSES = (
    PROVIDER_USAGE_REFRESH_RESERVED,
    PROVIDER_USAGE_REFRESH_JOINED,
)


class ProviderUsageStateError(RuntimeError):
    """Raised when provider-usage store state cannot be safely consumed."""


@dataclass(frozen=True)
class ProviderUsageStoreDiagnostic:
    """One non-secret provider-usage store diagnostic."""

    provider: str | None
    message: str

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageStoreDiagnostic:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError("provider-usage diagnostic is not an object")
        _require_exact_fields(payload, {"provider", "message"}, "diagnostic")
        provider = payload["provider"]
        message = payload["message"]
        if provider is not None and not is_provider_id(provider):
            raise ProviderUsageStateError(f"invalid diagnostic provider: {provider!r}")
        if not isinstance(message, str) or not message.strip():
            raise ProviderUsageStateError(
                "diagnostic message must be a non-empty string"
            )
        return cls(provider=provider, message=message)


@dataclass(frozen=True)
class ProviderUsageStoreRead:
    """Read-only public snapshot plus store-level diagnostics."""

    version: int
    snapshot: Mapping[str, Any]
    diagnostics: tuple[ProviderUsageStoreDiagnostic, ...]

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageStoreRead:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError("provider-usage store read is not an object")
        _require_exact_fields(
            payload, {"version", "snapshot", "diagnostics"}, "store read"
        )
        _require_version(payload["version"], "store read")
        snapshot = payload["snapshot"]
        diagnostics = payload["diagnostics"]
        if not isinstance(snapshot, dict):
            raise ProviderUsageStateError("provider-usage snapshot is not an object")
        if not isinstance(diagnostics, list):
            raise ProviderUsageStateError("provider-usage diagnostics must be a list")
        return cls(
            version=payload["version"],
            snapshot=snapshot,
            diagnostics=tuple(
                ProviderUsageStoreDiagnostic.from_wire(item) for item in diagnostics
            ),
        )


@dataclass(frozen=True)
class ProviderUsageStoreWriteOutcome:
    """Result of recording a provider usage observation."""

    version: int
    status: str
    accepted: bool
    provider: str
    account_generation: int
    reason: str | None

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageStoreWriteOutcome:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage write outcome is not an object"
            )
        _require_exact_fields(
            payload,
            {
                "version",
                "status",
                "accepted",
                "provider",
                "account_generation",
                "reason",
            },
            "write outcome",
        )
        _require_version(payload["version"], "write outcome")
        status = payload["status"]
        accepted = payload["accepted"]
        provider = payload["provider"]
        account_generation = payload["account_generation"]
        reason = payload["reason"]
        if status not in PROVIDER_USAGE_STORE_WRITE_STATUSES:
            raise ProviderUsageStateError(
                f"unknown provider-usage write status: {status!r}"
            )
        if type(accepted) is not bool:
            raise ProviderUsageStateError("write accepted must be a boolean")
        if not is_provider_id(provider):
            raise ProviderUsageStateError(f"invalid provider id: {provider!r}")
        if type(account_generation) is not int or account_generation < 0:
            raise ProviderUsageStateError(
                "account_generation must be a nonnegative integer"
            )
        if reason is not None and not isinstance(reason, str):
            raise ProviderUsageStateError("write reason must be a string or null")
        return cls(
            version=payload["version"],
            status=status,
            accepted=accepted,
            provider=provider,
            account_generation=account_generation,
            reason=reason,
        )


@dataclass(frozen=True)
class ProviderUsageAccountContext:
    """Generation-fenced account context for one provider."""

    version: int
    provider: str
    context_id: str
    account_generation: int
    changed: bool

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageAccountContext:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage account context is not an object"
            )
        _require_exact_fields(
            payload,
            {"version", "provider", "context_id", "account_generation", "changed"},
            "account context",
        )
        _require_version(payload["version"], "account context")
        provider = payload["provider"]
        context_id = payload["context_id"]
        account_generation = payload["account_generation"]
        changed = payload["changed"]
        if not is_provider_id(provider):
            raise ProviderUsageStateError(f"invalid provider id: {provider!r}")
        if not is_provider_id(context_id):
            raise ProviderUsageStateError(f"invalid context id: {context_id!r}")
        if type(account_generation) is not int or account_generation < 0:
            raise ProviderUsageStateError(
                "account_generation must be a nonnegative integer"
            )
        if type(changed) is not bool:
            raise ProviderUsageStateError("account context changed must be a boolean")
        return cls(
            version=payload["version"],
            provider=provider,
            context_id=context_id,
            account_generation=account_generation,
            changed=changed,
        )


@dataclass(frozen=True)
class ProviderUsageRefreshReservation:
    """One generation-fenced refresh reservation."""

    version: int
    provider: str
    context_id: str
    account_generation: int
    operation_id: str
    lease_id: str
    reserved_at: float
    expires_at: float

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageRefreshReservation:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError("provider-usage reservation is not an object")
        _require_exact_fields(
            payload,
            {
                "version",
                "provider",
                "context_id",
                "account_generation",
                "operation_id",
                "lease_id",
                "reserved_at",
                "expires_at",
            },
            "reservation",
        )
        _require_version(payload["version"], "reservation")
        provider = payload["provider"]
        context_id = payload["context_id"]
        account_generation = payload["account_generation"]
        operation_id = payload["operation_id"]
        lease_id = payload["lease_id"]
        reserved_at = payload["reserved_at"]
        expires_at = payload["expires_at"]
        for label, value in {
            "provider": provider,
            "context_id": context_id,
            "operation_id": operation_id,
            "lease_id": lease_id,
        }.items():
            if not is_provider_id(value):
                raise ProviderUsageStateError(f"invalid {label}: {value!r}")
        if type(account_generation) is not int or account_generation < 0:
            raise ProviderUsageStateError(
                "account_generation must be a nonnegative integer"
            )
        if not is_finite_number(reserved_at) or not is_finite_number(expires_at):
            raise ProviderUsageStateError(
                "reservation timestamps must be finite numbers"
            )
        if float(expires_at) <= float(reserved_at):
            raise ProviderUsageStateError(
                "reservation expires_at must follow reserved_at"
            )
        return cls(
            version=payload["version"],
            provider=provider,
            context_id=context_id,
            account_generation=account_generation,
            operation_id=operation_id,
            lease_id=lease_id,
            reserved_at=float(reserved_at),
            expires_at=float(expires_at),
        )


@dataclass(frozen=True)
class ProviderUsageRefreshReservationOutcome:
    """Result of reserving or joining refresh work."""

    version: int
    status: str
    reservation: ProviderUsageRefreshReservation

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageRefreshReservationOutcome:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage reservation outcome is not an object"
            )
        _require_exact_fields(
            payload, {"version", "status", "reservation"}, "reservation outcome"
        )
        _require_version(payload["version"], "reservation outcome")
        status = payload["status"]
        if status not in PROVIDER_USAGE_REFRESH_STATUSES:
            raise ProviderUsageStateError(
                f"unknown provider-usage reservation status: {status!r}"
            )
        return cls(
            version=payload["version"],
            status=status,
            reservation=ProviderUsageRefreshReservation.from_wire(
                payload["reservation"]
            ),
        )


def provider_usage_state_path() -> Path:
    """Return the canonical usage-state path under ``sase_home``."""
    binding = require_rust_binding("provider_usage_state_path")
    return Path(str(binding(str(sase_home()))))


def load_provider_usage(
    *,
    now: float | None = None,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    warn_percent: float = DEFAULT_USAGE_WARN_PERCENT,
    critical_percent: float = DEFAULT_USAGE_CRITICAL_PERCENT,
) -> ProviderUsageStoreRead:
    """Load the public usage snapshot without repairing or rewriting state."""
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_load")
    return ProviderUsageStoreRead.from_wire(
        binding(
            str(sase_home()),
            current,
            cadence_seconds,
            warn_percent,
            critical_percent,
        )
    )


def record_provider_usage_observation(
    observation: Mapping[str, object],
    *,
    now: float | None = None,
) -> ProviderUsageStoreWriteOutcome:
    """Validate, merge, and persist one normalized provider observation."""
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_record_observation")
    return ProviderUsageStoreWriteOutcome.from_wire(
        binding(str(sase_home()), dict(observation), current)
    )


def prepare_provider_usage_account_context(
    provider: str,
    context_id: str,
    *,
    now: float | None = None,
) -> ProviderUsageAccountContext:
    """Prepare or advance the generation fence for a provider account context."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_prepare_account_context")
    return ProviderUsageAccountContext.from_wire(
        binding(str(sase_home()), provider, context_id, current)
    )


def reserve_provider_usage_refresh(
    provider: str,
    context_id: str,
    account_generation: int,
    operation_id: str,
    ttl_seconds: float,
    *,
    now: float | None = None,
) -> ProviderUsageRefreshReservationOutcome:
    """Reserve or join refresh work for one provider/account generation."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    operation_id = _require_context_id(operation_id)
    account_generation = _require_account_generation(account_generation)
    if not is_finite_number(ttl_seconds) or float(ttl_seconds) <= 0.0:
        raise ValueError("ttl_seconds must be a finite positive number")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_reserve_refresh")
    return ProviderUsageRefreshReservationOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "operation_id": operation_id,
                "ttl_seconds": float(ttl_seconds),
            },
            current,
        )
    )


def release_provider_usage_refresh(
    provider: str,
    context_id: str,
    account_generation: int,
    lease_id: str,
    *,
    now: float | None = None,
) -> bool:
    """Release a refresh reservation when the lease still matches."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    lease_id = _require_context_id(lease_id)
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_release_refresh")
    return bool(
        binding(
            str(sase_home()),
            provider,
            context_id,
            account_generation,
            lease_id,
            current,
        )
    )


def _require_context_id(value: object) -> str:
    """Validate an opaque provider context, operation, or lease identifier."""
    if not isinstance(value, str):
        raise ValueError("context identifier must be a string")
    if not is_provider_id(value):
        raise ValueError("context identifier must be non-empty plain text")
    return value


def _require_account_generation(value: object) -> int:
    """Validate a generation fence value."""
    if type(value) is not int or value < 0:
        raise ValueError("account_generation must be a nonnegative integer")
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    required: set[str],
    label: str,
) -> None:
    if set(payload) == required:
        return
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - required)
    details: list[str] = []
    if missing:
        details.append(f"missing {', '.join(missing)}")
    if extra:
        details.append(f"unknown {', '.join(extra)}")
    raise ProviderUsageStateError(
        f"invalid provider-usage {label} fields: " + "; ".join(details)
    )


def _require_version(value: object, label: str) -> None:
    if type(value) is not int or value != PROVIDER_USAGE_STORE_SCHEMA_VERSION:
        raise ProviderUsageStateError(
            f"unsupported provider-usage {label} version: {value!r}"
        )


__all__ = [
    "DEFAULT_USAGE_CADENCE_SECONDS",
    "DEFAULT_USAGE_CRITICAL_PERCENT",
    "DEFAULT_USAGE_WARN_PERCENT",
    "PROVIDER_USAGE_OBSERVATION_SCHEMA_VERSION",
    "PROVIDER_USAGE_PUBLIC_SCHEMA_VERSION",
    "PROVIDER_USAGE_REFRESH_JOINED",
    "PROVIDER_USAGE_REFRESH_RESERVED",
    "PROVIDER_USAGE_REFRESH_STATUSES",
    "PROVIDER_USAGE_STATE_FILENAME",
    "PROVIDER_USAGE_STORE_SCHEMA_VERSION",
    "PROVIDER_USAGE_STORE_WRITE_RECORDED",
    "PROVIDER_USAGE_STORE_WRITE_STALE_WRITER",
    "PROVIDER_USAGE_STORE_WRITE_STATUSES",
    "PROVIDER_USAGE_STORE_WRITE_UNCHANGED",
    "ProviderUsageAccountContext",
    "ProviderUsageRefreshReservation",
    "ProviderUsageRefreshReservationOutcome",
    "ProviderUsageStateError",
    "ProviderUsageStoreDiagnostic",
    "ProviderUsageStoreRead",
    "ProviderUsageStoreWriteOutcome",
    "load_provider_usage",
    "prepare_provider_usage_account_context",
    "provider_usage_state_path",
    "record_provider_usage_observation",
    "release_provider_usage_refresh",
    "reserve_provider_usage_refresh",
]

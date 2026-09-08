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
PROVIDER_USAGE_REFRESH_DEFERRED = "deferred"
PROVIDER_USAGE_REFRESH_STATUSES = (
    PROVIDER_USAGE_REFRESH_RESERVED,
    PROVIDER_USAGE_REFRESH_JOINED,
)
PROVIDER_USAGE_REFRESH_ADMIT_STATUSES = (
    PROVIDER_USAGE_REFRESH_RESERVED,
    PROVIDER_USAGE_REFRESH_JOINED,
    PROVIDER_USAGE_REFRESH_DEFERRED,
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


@dataclass(frozen=True)
class ProviderUsageRefreshDueOutcome:
    """Whether one provider/context generation is due for refresh."""

    version: int
    due: bool
    reason: str
    due_at: float | None

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageRefreshDueOutcome:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError("provider-usage due outcome is not an object")
        _require_exact_fields(
            payload, {"version", "due", "reason", "due_at"}, "due outcome"
        )
        _require_version(payload["version"], "due outcome")
        due = payload["due"]
        reason = payload["reason"]
        due_at = payload["due_at"]
        if type(due) is not bool:
            raise ProviderUsageStateError("due must be a boolean")
        if not isinstance(reason, str) or not reason.strip():
            raise ProviderUsageStateError("due reason must be a non-empty string")
        if due_at is not None and not is_finite_number(due_at):
            raise ProviderUsageStateError("due_at must be a finite number or null")
        return cls(
            version=payload["version"],
            due=due,
            reason=reason,
            due_at=None if due_at is None else float(due_at),
        )


@dataclass(frozen=True)
class ProviderUsageRefreshAdmitOutcome:
    """Result of admitting refresh work under due/backoff policy."""

    version: int
    status: str
    reason: str | None
    due_at: float | None
    reservation: ProviderUsageRefreshReservation | None

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageRefreshAdmitOutcome:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage admit outcome is not an object"
            )
        _require_exact_fields(
            payload,
            {"version", "status", "reason", "due_at", "reservation"},
            "admit outcome",
        )
        _require_version(payload["version"], "admit outcome")
        status = payload["status"]
        reason = payload["reason"]
        due_at = payload["due_at"]
        reservation = payload["reservation"]
        if status not in PROVIDER_USAGE_REFRESH_ADMIT_STATUSES:
            raise ProviderUsageStateError(
                f"unknown provider-usage admission status: {status!r}"
            )
        if reason is not None and not isinstance(reason, str):
            raise ProviderUsageStateError("admit reason must be a string or null")
        if due_at is not None and not is_finite_number(due_at):
            raise ProviderUsageStateError("due_at must be a finite number or null")
        parsed: ProviderUsageRefreshReservation | None = None
        if reservation is not None:
            parsed = ProviderUsageRefreshReservation.from_wire(reservation)
        if status != PROVIDER_USAGE_REFRESH_DEFERRED and parsed is None:
            raise ProviderUsageStateError("admitted refresh is missing a reservation")
        return cls(
            version=payload["version"],
            status=status,
            reason=reason,
            due_at=None if due_at is None else float(due_at),
            reservation=parsed,
        )


@dataclass(frozen=True)
class ProviderUsageRefreshMarkDueOutcome:
    """Result of marking a provider due for refresh."""

    version: int
    marked: bool
    due_at: float
    reason: str

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageRefreshMarkDueOutcome:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage mark-due outcome is not an object"
            )
        _require_exact_fields(
            payload, {"version", "marked", "due_at", "reason"}, "mark-due outcome"
        )
        _require_version(payload["version"], "mark-due outcome")
        marked = payload["marked"]
        due_at = payload["due_at"]
        reason = payload["reason"]
        if type(marked) is not bool:
            raise ProviderUsageStateError("marked must be a boolean")
        if not is_finite_number(due_at):
            raise ProviderUsageStateError("due_at must be a finite number")
        if not isinstance(reason, str) or not reason.strip():
            raise ProviderUsageStateError("mark-due reason must be a non-empty string")
        return cls(
            version=payload["version"],
            marked=marked,
            due_at=float(due_at),
            reason=reason,
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


def evaluate_provider_usage_refresh_due(
    provider: str,
    context_id: str,
    account_generation: int,
    *,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    explicit: bool = False,
    now: float | None = None,
) -> ProviderUsageRefreshDueOutcome:
    """Return whether *provider* is due without reserving work."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    if not is_finite_number(cadence_seconds) or float(cadence_seconds) <= 0.0:
        raise ValueError("cadence_seconds must be a finite positive number")
    if type(explicit) is not bool:
        raise ValueError("explicit must be a boolean")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_refresh_due")
    return ProviderUsageRefreshDueOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "cadence_seconds": float(cadence_seconds),
                "explicit": explicit,
            },
            current,
        )
    )


def admit_provider_usage_refresh(
    provider: str,
    context_id: str,
    account_generation: int,
    operation_id: str,
    ttl_seconds: float,
    *,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    explicit: bool = False,
    now: float | None = None,
) -> ProviderUsageRefreshAdmitOutcome:
    """Admit, join, or defer refresh work for one provider/account generation."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    operation_id = _require_context_id(operation_id)
    account_generation = _require_account_generation(account_generation)
    if not is_finite_number(ttl_seconds) or float(ttl_seconds) <= 0.0:
        raise ValueError("ttl_seconds must be a finite positive number")
    if not is_finite_number(cadence_seconds) or float(cadence_seconds) <= 0.0:
        raise ValueError("cadence_seconds must be a finite positive number")
    if type(explicit) is not bool:
        raise ValueError("explicit must be a boolean")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_admit_refresh")
    return ProviderUsageRefreshAdmitOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "operation_id": operation_id,
                "ttl_seconds": float(ttl_seconds),
                "cadence_seconds": float(cadence_seconds),
                "explicit": explicit,
            },
            current,
        )
    )


def mark_provider_usage_refresh_due(
    provider: str,
    context_id: str,
    account_generation: int,
    reason: str,
    *,
    due_at: float | None = None,
    now: float | None = None,
) -> ProviderUsageRefreshMarkDueOutcome:
    """Mark *provider* due once for *reason*, optionally at a future time."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    if due_at is not None and not is_finite_number(due_at):
        raise ValueError("due_at must be a finite number")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_mark_refresh_due")
    return ProviderUsageRefreshMarkDueOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "reason": reason.strip(),
                "due_at": None if due_at is None else float(due_at),
            },
            current,
        )
    )


def record_provider_usage_refresh_attempt(
    provider: str,
    context_id: str,
    account_generation: int,
    outcome: str,
    *,
    retry_after_seconds: float | None = None,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    now: float | None = None,
) -> dict[str, Any]:
    """Record backoff/cooldown after one provider refresh attempt."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    if not isinstance(outcome, str) or not outcome.strip():
        raise ValueError("outcome must be a non-empty string")
    if retry_after_seconds is not None and (
        not is_finite_number(retry_after_seconds) or float(retry_after_seconds) < 0.0
    ):
        raise ValueError("retry_after_seconds must be a finite nonnegative number")
    if not is_finite_number(cadence_seconds) or float(cadence_seconds) <= 0.0:
        raise ValueError("cadence_seconds must be a finite positive number")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_record_refresh_attempt")
    recorded = binding(
        str(sase_home()),
        {
            "provider": provider,
            "context_id": context_id,
            "account_generation": account_generation,
            "outcome": outcome.strip(),
            "retry_after_seconds": (
                None if retry_after_seconds is None else float(retry_after_seconds)
            ),
            "cadence_seconds": float(cadence_seconds),
        },
        current,
    )
    if not isinstance(recorded, dict):
        raise ProviderUsageStateError("refresh attempt record is not an object")
    return recorded


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
    "PROVIDER_USAGE_REFRESH_ADMIT_STATUSES",
    "PROVIDER_USAGE_REFRESH_DEFERRED",
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
    "ProviderUsageRefreshAdmitOutcome",
    "ProviderUsageRefreshDueOutcome",
    "ProviderUsageRefreshMarkDueOutcome",
    "ProviderUsageRefreshReservation",
    "ProviderUsageRefreshReservationOutcome",
    "ProviderUsageStateError",
    "ProviderUsageStoreDiagnostic",
    "ProviderUsageStoreRead",
    "ProviderUsageStoreWriteOutcome",
    "admit_provider_usage_refresh",
    "evaluate_provider_usage_refresh_due",
    "load_provider_usage",
    "mark_provider_usage_refresh_due",
    "prepare_provider_usage_account_context",
    "provider_usage_state_path",
    "record_provider_usage_observation",
    "record_provider_usage_refresh_attempt",
    "release_provider_usage_refresh",
    "reserve_provider_usage_refresh",
]

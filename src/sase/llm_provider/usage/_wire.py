"""Wire records and validation for provider usage store responses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.llm_provider.provider_disable import is_finite_number, is_provider_id
from sase.llm_provider.usage.constants import (
    PROVIDER_USAGE_INDICATOR_SCHEMA_VERSION,
    PROVIDER_USAGE_REFRESH_ADMIT_STATUSES,
    PROVIDER_USAGE_REFRESH_DEFERRED,
    PROVIDER_USAGE_REFRESH_STATUSES,
    PROVIDER_USAGE_STORE_SCHEMA_VERSION,
    PROVIDER_USAGE_STORE_WRITE_STATUSES,
)
from sase.llm_provider.usage.errors import ProviderUsageStateError


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
class ProviderUsageIndicatorDiagnostic:
    """One provider-usage indicator config or projection diagnostic."""

    path: str
    message: str

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageIndicatorDiagnostic:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError("usage indicator diagnostic is not an object")
        _require_exact_fields(payload, {"path", "message"}, "indicator diagnostic")
        path = payload["path"]
        message = payload["message"]
        if not isinstance(path, str) or not path.strip():
            raise ProviderUsageStateError(
                "usage indicator diagnostic path must be a non-empty string"
            )
        if not isinstance(message, str) or not message.strip():
            raise ProviderUsageStateError(
                "usage indicator diagnostic message must be a non-empty string"
            )
        return cls(path=path, message=message)


@dataclass(frozen=True)
class ProviderUsageIndicatorConfigValidation:
    """Normalized indicator config plus bounded diagnostics from Rust core."""

    schema_version: int
    config: Mapping[str, Any]
    diagnostics: tuple[ProviderUsageIndicatorDiagnostic, ...]

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageIndicatorConfigValidation:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage indicator validation is not an object"
            )
        _require_exact_fields(
            payload,
            {"schema_version", "config", "diagnostics"},
            "indicator validation",
        )
        _require_indicator_version(payload["schema_version"], "indicator validation")
        config = payload["config"]
        diagnostics = payload["diagnostics"]
        if not isinstance(config, dict):
            raise ProviderUsageStateError("usage indicator config is not an object")
        if not isinstance(diagnostics, list):
            raise ProviderUsageStateError("usage indicator diagnostics must be a list")
        return cls(
            schema_version=payload["schema_version"],
            config=config,
            diagnostics=tuple(
                ProviderUsageIndicatorDiagnostic.from_wire(item) for item in diagnostics
            ),
        )


@dataclass(frozen=True)
class ProviderUsageIndicatorProjection:
    """Selected usage-window records and provider health for top-bar display."""

    schema_version: int
    generated_at: float
    enabled: bool
    diagnostics: tuple[ProviderUsageIndicatorDiagnostic, ...]
    providers: tuple[Mapping[str, Any], ...]
    entries: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_wire(cls, payload: object) -> ProviderUsageIndicatorProjection:
        if not isinstance(payload, dict):
            raise ProviderUsageStateError(
                "provider-usage indicator projection is not an object"
            )
        _require_exact_fields(
            payload,
            {
                "schema_version",
                "generated_at",
                "enabled",
                "diagnostics",
                "providers",
                "entries",
            },
            "indicator projection",
        )
        _require_indicator_version(payload["schema_version"], "indicator projection")
        generated_at = payload["generated_at"]
        enabled = payload["enabled"]
        diagnostics = payload["diagnostics"]
        providers = payload["providers"]
        entries = payload["entries"]
        if not is_finite_number(generated_at):
            raise ProviderUsageStateError("usage indicator generated_at must be finite")
        if type(enabled) is not bool:
            raise ProviderUsageStateError("usage indicator enabled must be boolean")
        if not isinstance(diagnostics, list):
            raise ProviderUsageStateError("usage indicator diagnostics must be a list")
        if not isinstance(providers, list) or not all(
            isinstance(item, dict) for item in providers
        ):
            raise ProviderUsageStateError(
                "usage indicator providers must be a list of objects"
            )
        if not isinstance(entries, list) or not all(
            isinstance(item, dict) for item in entries
        ):
            raise ProviderUsageStateError(
                "usage indicator entries must be a list of objects"
            )
        return cls(
            schema_version=payload["schema_version"],
            generated_at=float(generated_at),
            enabled=enabled,
            diagnostics=tuple(
                ProviderUsageIndicatorDiagnostic.from_wire(item) for item in diagnostics
            ),
            providers=tuple(providers),
            entries=tuple(entries),
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


def _require_indicator_version(value: object, label: str) -> None:
    if type(value) is not int or value != PROVIDER_USAGE_INDICATOR_SCHEMA_VERSION:
        raise ProviderUsageStateError(
            f"unsupported provider-usage {label} version: {value!r}"
        )


__all__ = [
    "ProviderUsageAccountContext",
    "ProviderUsageIndicatorConfigValidation",
    "ProviderUsageIndicatorDiagnostic",
    "ProviderUsageIndicatorProjection",
    "ProviderUsageRefreshAdmitOutcome",
    "ProviderUsageRefreshDueOutcome",
    "ProviderUsageRefreshMarkDueOutcome",
    "ProviderUsageRefreshReservation",
    "ProviderUsageRefreshReservationOutcome",
    "ProviderUsageStoreDiagnostic",
    "ProviderUsageStoreRead",
    "ProviderUsageStoreWriteOutcome",
]

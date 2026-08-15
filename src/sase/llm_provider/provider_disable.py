"""Rust-backed temporary LLM provider-disable facade."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

PROVIDER_DISABLE_WIRE_SCHEMA_VERSION = 1


class ProviderDisableStateError(RuntimeError):
    """Raised when provider-disable state cannot be safely consumed."""


@dataclass(frozen=True)
class TemporaryProviderDisable:
    """One active machine-wide provider disable."""

    version: int
    provider: str
    created_at: float
    expires_at: float | None
    source: str

    @classmethod
    def from_wire(cls, payload: object) -> TemporaryProviderDisable:
        """Strictly rehydrate the stable Rust wire record."""
        if not isinstance(payload, dict):
            raise ProviderDisableStateError("provider-disable record is not an object")
        required = {"version", "provider", "created_at", "expires_at", "source"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise ProviderDisableStateError(
                "invalid provider-disable fields: " + "; ".join(details)
            )

        version = payload["version"]
        provider = payload["provider"]
        created_at = payload["created_at"]
        expires_at = payload["expires_at"]
        source = payload["source"]
        if type(version) is not int or version != PROVIDER_DISABLE_WIRE_SCHEMA_VERSION:
            raise ProviderDisableStateError(
                f"unsupported provider-disable wire version: {version!r}"
            )
        if not _is_provider_id(provider):
            raise ProviderDisableStateError(f"invalid provider id: {provider!r}")
        if not _is_finite_number(created_at) or float(created_at) <= 0.0:
            raise ProviderDisableStateError(
                "created_at must be a finite positive number"
            )
        if expires_at is not None and not _is_finite_number(expires_at):
            raise ProviderDisableStateError(
                "expires_at must be a finite number or null"
            )
        if expires_at is not None and float(expires_at) <= float(created_at):
            raise ProviderDisableStateError("expires_at must be later than created_at")
        if not isinstance(source, str) or not source.strip():
            raise ProviderDisableStateError("source must be a non-empty string")
        return cls(
            version=version,
            provider=provider,
            created_at=float(created_at),
            expires_at=float(expires_at) if expires_at is not None else None,
            source=source,
        )

    def is_active(self, now: float) -> bool:
        """Return whether this captured record is still active at *now*."""
        return self.expires_at is None or now < self.expires_at


def get_active_provider_disables(
    now: float | None = None,
) -> dict[str, TemporaryProviderDisable]:
    """Return every active provider disable, self-cleaning stale state."""
    binding = require_rust_binding("provider_disable_get")
    payload: Any = binding(str(sase_home()), now)
    return _snapshot_from_wire(payload)


def get_active_provider_disable(
    provider: str,
    now: float | None = None,
) -> TemporaryProviderDisable | None:
    """Return the active disable for *provider*, or ``None`` if absent."""
    if not _is_provider_id(provider):
        return None
    return get_active_provider_disables(now).get(provider)


def disable_provider(
    provider: str,
    duration_seconds: float | None,
    *,
    source: str,
    now: float | None = None,
) -> TemporaryProviderDisable:
    """Disable a registered provider for a relative duration or until cleared."""
    provider = _require_registered_provider(provider)
    binding = require_rust_binding("provider_disable_set_relative")
    payload: Any = binding(
        str(sase_home()),
        provider,
        source,
        duration_seconds,
        now,
    )
    return TemporaryProviderDisable.from_wire(payload)


def disable_provider_until(
    provider: str,
    expires_at: float,
    *,
    source: str,
    now: float | None = None,
) -> TemporaryProviderDisable:
    """Disable a registered provider until an exact Unix timestamp."""
    provider = _require_registered_provider(provider)
    binding = require_rust_binding("provider_disable_set_until")
    payload: Any = binding(str(sase_home()), provider, expires_at, source, now)
    return TemporaryProviderDisable.from_wire(payload)


def enable_provider(provider: str) -> bool:
    """Idempotently clear one provider disable.

    Clearing validates only provider-id syntax so state remains clearable after
    a provider plugin is uninstalled.
    """
    provider = _require_provider_id(provider)
    binding = require_rust_binding("provider_disable_clear")
    return bool(binding(str(sase_home()), provider))


def _snapshot_from_wire(payload: object) -> dict[str, TemporaryProviderDisable]:
    if not isinstance(payload, dict):
        raise ProviderDisableStateError("provider-disable snapshot is not an object")
    required = {"version", "disables"}
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise ProviderDisableStateError(
            "invalid provider-disable snapshot fields: " + "; ".join(details)
        )
    version = payload["version"]
    if type(version) is not int or version != PROVIDER_DISABLE_WIRE_SCHEMA_VERSION:
        raise ProviderDisableStateError(
            f"unsupported provider-disable snapshot version: {version!r}"
        )
    raw_records = payload["disables"]
    if not isinstance(raw_records, list):
        raise ProviderDisableStateError("snapshot disables must be a list")

    result: dict[str, TemporaryProviderDisable] = {}
    providers: list[str] = []
    for raw in raw_records:
        record = TemporaryProviderDisable.from_wire(raw)
        if record.provider in result:
            raise ProviderDisableStateError(
                f"duplicate provider-disable record: {record.provider!r}"
            )
        result[record.provider] = record
        providers.append(record.provider)
    if providers != sorted(providers):
        raise ProviderDisableStateError(
            "provider-disable snapshot is not sorted by provider"
        )
    return result


def _require_registered_provider(provider: str) -> str:
    provider = _require_provider_id(provider)
    from .registry import registered_provider_names

    registered = registered_provider_names()
    if provider not in registered:
        raise ValueError(
            f"unknown LLM provider: {provider!r}. "
            f"Registered providers: {sorted(registered)}"
        )
    return provider


def _require_provider_id(provider: object) -> str:
    if not isinstance(provider, str):
        raise ValueError("provider must be a string")
    if not _is_provider_id(provider):
        raise ValueError("provider must be a non-empty provider id")
    return provider


def _is_provider_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


__all__ = [
    "PROVIDER_DISABLE_WIRE_SCHEMA_VERSION",
    "ProviderDisableStateError",
    "TemporaryProviderDisable",
    "disable_provider",
    "disable_provider_until",
    "enable_provider",
    "get_active_provider_disable",
    "get_active_provider_disables",
]

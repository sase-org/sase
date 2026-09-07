"""Wire records for temporary LLM provider-priority state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .provider_disable import is_finite_number, is_provider_id

PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION = 1
PROVIDER_PRIORITY_DECODE_WIRE_SCHEMA_VERSION = 1
PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION = 1

ProviderPriorityWriteStatus = Literal[
    "changed",
    "unchanged",
    "ineligible_target",
    "conflict",
]

_PROVIDER_PRIORITY_WRITE_STATUSES = {
    "changed",
    "unchanged",
    "ineligible_target",
    "conflict",
}


class ProviderPriorityStateError(RuntimeError):
    """Raised when provider-priority routing state cannot be consumed."""


@dataclass(frozen=True, slots=True)
class TemporaryProviderPriority:
    """One active machine-wide provider priority."""

    version: int
    provider: str
    created_at: float
    expires_at: float | None
    source: str

    @classmethod
    def from_wire(cls, payload: object) -> TemporaryProviderPriority:
        """Strictly rehydrate the stable Rust wire record."""
        if not isinstance(payload, dict):
            raise ProviderPriorityStateError(
                "provider-priority record is not an object"
            )
        required = {"version", "provider", "created_at", "expires_at", "source"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise ProviderPriorityStateError(
                "invalid provider-priority fields: " + "; ".join(details)
            )

        version = payload["version"]
        provider = payload["provider"]
        created_at = payload["created_at"]
        expires_at = payload["expires_at"]
        source = payload["source"]
        if type(version) is not int or version != PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION:
            raise ProviderPriorityStateError(
                f"unsupported provider-priority wire version: {version!r}"
            )
        if not is_provider_id(provider):
            raise ProviderPriorityStateError(f"invalid provider id: {provider!r}")
        if not is_finite_number(created_at) or float(created_at) <= 0.0:
            raise ProviderPriorityStateError(
                "created_at must be a finite positive number"
            )
        if expires_at is not None and not is_finite_number(expires_at):
            raise ProviderPriorityStateError(
                "expires_at must be a finite number or null"
            )
        if expires_at is not None and float(expires_at) <= float(created_at):
            raise ProviderPriorityStateError("expires_at must be later than created_at")
        if not isinstance(source, str) or not source.strip():
            raise ProviderPriorityStateError("source must be a non-empty string")
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

    def to_wire(self) -> dict[str, object]:
        """Return the exact stable Rust wire shape."""
        return {
            "version": self.version,
            "provider": self.provider,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ProviderPriorityDecode:
    """Lock-free decode result for provider-priority display reads."""

    version: int
    priority: TemporaryProviderPriority | None
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, payload: object) -> ProviderPriorityDecode:
        """Strictly rehydrate the Rust decode envelope."""
        if not isinstance(payload, dict):
            raise ProviderPriorityStateError(
                "provider-priority decode is not an object"
            )
        required = {"version", "priority", "diagnostics"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise ProviderPriorityStateError(
                "invalid provider-priority decode fields: " + "; ".join(details)
            )
        version = payload["version"]
        if (
            type(version) is not int
            or version != PROVIDER_PRIORITY_DECODE_WIRE_SCHEMA_VERSION
        ):
            raise ProviderPriorityStateError(
                f"unsupported provider-priority decode version: {version!r}"
            )
        diagnostics = _diagnostics_from_wire(payload["diagnostics"])
        priority = payload["priority"]
        return cls(
            version=version,
            priority=(
                TemporaryProviderPriority.from_wire(priority)
                if priority is not None
                else None
            ),
            diagnostics=diagnostics,
        )


@dataclass(frozen=True, slots=True)
class ProviderPriorityWriteOutcome:
    """Result of a conditional provider-priority write."""

    version: int
    status: ProviderPriorityWriteStatus
    record: TemporaryProviderPriority | None
    current: TemporaryProviderPriority | None
    reason: str | None = None

    @classmethod
    def from_wire(cls, payload: object) -> ProviderPriorityWriteOutcome:
        """Strictly rehydrate the Rust priority-write outcome envelope."""
        if not isinstance(payload, dict):
            raise ProviderPriorityStateError(
                "provider-priority write outcome is not an object"
            )
        required = {"version", "status", "record", "current", "reason"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise ProviderPriorityStateError(
                "invalid provider-priority write outcome fields: " + "; ".join(details)
            )
        version = payload["version"]
        if (
            type(version) is not int
            or version != PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION
        ):
            raise ProviderPriorityStateError(
                f"unsupported provider-priority write outcome version: {version!r}"
            )
        status = payload["status"]
        if status not in _PROVIDER_PRIORITY_WRITE_STATUSES:
            raise ProviderPriorityStateError(
                f"unsupported provider-priority write status: {status!r}"
            )
        reason = payload["reason"]
        if reason is not None and not isinstance(reason, str):
            raise ProviderPriorityStateError("reason must be a string or null")
        return cls(
            version=version,
            status=status,
            record=_priority_or_none(payload["record"]),
            current=_priority_or_none(payload["current"]),
            reason=reason,
        )


def provider_priority_route_key(
    priority: TemporaryProviderPriority | None,
) -> tuple[object, ...] | None:
    """Return a compact comparison key for an active priority record."""
    if priority is None:
        return None
    return (
        priority.provider,
        priority.created_at,
        priority.expires_at,
        priority.source,
    )


def _priority_or_none(payload: object) -> TemporaryProviderPriority | None:
    if payload is None:
        return None
    return TemporaryProviderPriority.from_wire(payload)


def _diagnostics_from_wire(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise ProviderPriorityStateError("diagnostics must be a list of strings")
    return tuple(payload)

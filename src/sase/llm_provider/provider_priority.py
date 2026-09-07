"""Rust-backed temporary LLM provider-priority facade."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

from .load_balancing import MemberAvailability
from .provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
    is_finite_number,
    is_provider_id,
    require_provider_id,
    require_registered_provider,
)

PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION = 1
PROVIDER_PRIORITY_DECODE_WIRE_SCHEMA_VERSION = 1
PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION = 1
PROVIDER_ROUTING_CONTEXT_WIRE_SCHEMA_VERSION = 1
PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION = 1

PROVIDER_PRIORITY_STATE_FILENAME = "llm_provider_priority.json"

ProviderDisableSnapshot = Mapping[str, TemporaryProviderDisable]
ProviderAvailabilityProvenance = Literal[
    "ordinary_available",
    "unregistered",
    "not_user_facing",
    "cli_missing",
    "actual_hard_disable",
    "actual_soft_disable",
    "priority",
    "priority_backup",
]
ProviderPriorityWriteStatus = Literal[
    "changed",
    "unchanged",
    "ineligible_target",
    "conflict",
]

_PROVIDER_AVAILABILITY_PROVENANCE_VALUES = {
    "ordinary_available",
    "unregistered",
    "not_user_facing",
    "cli_missing",
    "actual_hard_disable",
    "actual_soft_disable",
    "priority",
    "priority_backup",
}
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


@dataclass(frozen=True, slots=True)
class ProviderRoutingContext:
    """Actual disables and priority captured once for one routing decision."""

    version: int
    captured_at: float
    provider_disables: dict[str, TemporaryProviderDisable]
    priority: TemporaryProviderPriority | None
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, payload: object) -> ProviderRoutingContext:
        """Strictly rehydrate a Rust routing-context wire envelope."""
        if not isinstance(payload, dict):
            raise ProviderPriorityStateError(
                "provider-routing context is not an object"
            )
        required = {"version", "captured_at", "disables", "priority", "diagnostics"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise ProviderPriorityStateError(
                "invalid provider-routing context fields: " + "; ".join(details)
            )
        version = payload["version"]
        if (
            type(version) is not int
            or version != PROVIDER_ROUTING_CONTEXT_WIRE_SCHEMA_VERSION
        ):
            raise ProviderPriorityStateError(
                f"unsupported provider-routing context version: {version!r}"
            )
        captured_at = payload["captured_at"]
        if not is_finite_number(captured_at) or float(captured_at) < 0.0:
            raise ProviderPriorityStateError(
                "captured_at must be a finite non-negative number"
            )
        raw_disables = payload["disables"]
        if not isinstance(raw_disables, list):
            raise ProviderPriorityStateError("context disables must be a list")
        disables: dict[str, TemporaryProviderDisable] = {}
        providers: list[str] = []
        for raw in raw_disables:
            record = TemporaryProviderDisable.from_wire(raw)
            if record.provider in disables:
                raise ProviderPriorityStateError(
                    f"duplicate provider-disable record: {record.provider!r}"
                )
            disables[record.provider] = record
            providers.append(record.provider)
        if providers != sorted(providers):
            raise ProviderPriorityStateError(
                "provider-routing context is not sorted by provider"
            )
        return cls(
            version=version,
            captured_at=float(captured_at),
            provider_disables=disables,
            priority=_priority_or_none(payload["priority"]),
            diagnostics=_diagnostics_from_wire(payload["diagnostics"]),
        )

    @property
    def disables(self) -> Mapping[str, TemporaryProviderDisable]:
        """Compatibility alias for actual provider disables."""
        return self.provider_disables

    def to_wire(self) -> dict[str, object]:
        """Return the exact stable Rust wire shape for pure classifications."""
        return {
            "version": self.version,
            "captured_at": self.captured_at,
            "disables": [
                _provider_disable_to_wire(record)
                for _provider, record in sorted(self.provider_disables.items())
            ],
            "priority": self.priority.to_wire() if self.priority is not None else None,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    """Pure effective availability classification for one provider."""

    version: int
    provider: str
    availability: MemberAvailability
    provenance: tuple[ProviderAvailabilityProvenance, ...]
    actual_disable: TemporaryProviderDisable | None
    priority: TemporaryProviderPriority | None
    eligible_for_priority: bool

    @classmethod
    def from_wire(cls, payload: object) -> ProviderAvailability:
        """Strictly rehydrate the stable Rust availability wire shape."""
        if not isinstance(payload, dict):
            raise ProviderPriorityStateError("provider availability is not an object")
        required = {
            "version",
            "provider",
            "availability",
            "provenance",
            "actual_disable",
            "priority",
            "eligible_for_priority",
        }
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise ProviderPriorityStateError(
                "invalid provider-availability fields: " + "; ".join(details)
            )
        version = payload["version"]
        if (
            type(version) is not int
            or version != PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION
        ):
            raise ProviderPriorityStateError(
                f"unsupported provider-availability version: {version!r}"
            )
        provider = payload["provider"]
        if not is_provider_id(provider):
            raise ProviderPriorityStateError(f"invalid provider id: {provider!r}")
        availability = payload["availability"]
        if availability not in {item.value for item in MemberAvailability}:
            raise ProviderPriorityStateError(
                f"unsupported provider availability: {availability!r}"
            )
        provenance = _provenance_from_wire(payload["provenance"])
        eligible_for_priority = payload["eligible_for_priority"]
        if type(eligible_for_priority) is not bool:
            raise ProviderPriorityStateError("eligible_for_priority must be a boolean")
        return cls(
            version=version,
            provider=provider,
            availability=MemberAvailability(availability),
            provenance=provenance,
            actual_disable=_disable_or_none(payload["actual_disable"]),
            priority=_priority_or_none(payload["priority"]),
            eligible_for_priority=eligible_for_priority,
        )


def provider_priority_state_path() -> Path:
    """Return the canonical priority-state path under ``sase_home``."""
    return sase_home() / PROVIDER_PRIORITY_STATE_FILENAME


def get_active_provider_priority(
    now: float | None = None,
) -> TemporaryProviderPriority | None:
    """Return the active provider priority, self-cleaning stale state."""
    binding = require_rust_binding("provider_priority_get")
    payload: Any = binding(str(sase_home()), now)
    return _priority_or_none(payload)


def decode_provider_priority(
    data: bytes | None,
    *,
    now: float | None = None,
) -> ProviderPriorityDecode:
    """Decode provider-priority bytes without filesystem or locking effects."""
    binding = require_rust_binding("provider_priority_decode")
    payload: Any = binding(data, now)
    return ProviderPriorityDecode.from_wire(payload)


def set_provider_priority(
    provider: str,
    duration_seconds: float | None,
    *,
    source: str,
    facts: Mapping[str, object],
    expected: TemporaryProviderPriority | None = None,
    now: float | None = None,
) -> ProviderPriorityWriteOutcome:
    """Set or replace priority for a relative duration."""
    provider = require_registered_provider(provider)
    binding = require_rust_binding("provider_priority_set_relative")
    payload: Any = binding(
        str(sase_home()),
        provider,
        source,
        _priority_facts_to_wire(provider, facts),
        _priority_to_wire(expected),
        duration_seconds,
        now,
    )
    return ProviderPriorityWriteOutcome.from_wire(payload)


def set_provider_priority_until(
    provider: str,
    expires_at: float,
    *,
    source: str,
    facts: Mapping[str, object],
    expected: TemporaryProviderPriority | None = None,
    now: float | None = None,
) -> ProviderPriorityWriteOutcome:
    """Set or replace priority until an exact Unix timestamp."""
    provider = require_registered_provider(provider)
    binding = require_rust_binding("provider_priority_set_until")
    payload: Any = binding(
        str(sase_home()),
        provider,
        expires_at,
        source,
        _priority_facts_to_wire(provider, facts),
        _priority_to_wire(expected),
        now,
    )
    return ProviderPriorityWriteOutcome.from_wire(payload)


def clear_provider_priority(
    *,
    expected: TemporaryProviderPriority | None = None,
    now: float | None = None,
) -> ProviderPriorityWriteOutcome:
    """Clear priority when the live state matches *expected*."""
    binding = require_rust_binding("provider_priority_clear")
    payload: Any = binding(str(sase_home()), _priority_to_wire(expected), now)
    return ProviderPriorityWriteOutcome.from_wire(payload)


def capture_provider_routing_context(
    now: float | None = None,
) -> ProviderRoutingContext:
    """Capture actual disables and priority under one routing-state lock."""
    binding = require_rust_binding("provider_routing_context_get")
    payload: Any = binding(str(sase_home()), _binding_capture_now(now))
    return ProviderRoutingContext.from_wire(payload)


def provider_routing_context_from_parts(
    provider_disables: ProviderDisableSnapshot | None,
    priority: TemporaryProviderPriority | None,
    *,
    captured_at: float | None = None,
) -> ProviderRoutingContext:
    """Build a routing context from already-decoded parts without filesystem I/O."""
    binding = require_rust_binding("provider_routing_context_from_parts")
    disables = provider_disables or {}
    capture_time = (
        _default_parts_captured_at(disables, priority)
        if captured_at is None
        else captured_at
    )
    payload: Any = binding(
        _provider_disables_to_wire(disables),
        _priority_to_wire(priority),
        capture_time,
    )
    return ProviderRoutingContext.from_wire(payload)


def resolve_provider_routing_context(
    *,
    routing_context: ProviderRoutingContext | None = None,
    provider_disables: ProviderDisableSnapshot | None = None,
    now: float | None = None,
) -> ProviderRoutingContext:
    """Return one explicit or freshly captured routing context.

    Passing ``provider_disables`` is legacy disable-only routing: ambient
    priority is intentionally not recaptured for that call. Passing both
    explicit inputs is rejected so callers do not mix two different snapshots.
    """
    if routing_context is not None and provider_disables is not None:
        raise ValueError("pass routing_context or provider_disables, not both")
    if routing_context is not None:
        return routing_context
    if provider_disables is not None:
        return provider_routing_context_from_parts(
            provider_disables,
            None,
            captured_at=_binding_capture_now(now),
        )
    return capture_provider_routing_context(now)


def _binding_capture_now(now: float | None) -> float | None:
    """Normalize legacy test sentinels before calling Rust routing capture APIs."""
    if now is not None and now <= 0.0:
        return None
    return now


def _default_parts_captured_at(
    provider_disables: ProviderDisableSnapshot,
    priority: TemporaryProviderPriority | None,
) -> float:
    """Pick a stable active clock for explicit, already-decoded routing parts."""
    lower_bound = 0.000001
    deadlines: list[float] = []
    for record in provider_disables.values():
        lower_bound = max(lower_bound, record.created_at)
        if record.expires_at is not None:
            deadlines.append(record.expires_at)
    if priority is not None:
        lower_bound = max(lower_bound, priority.created_at)
        if priority.expires_at is not None:
            deadlines.append(priority.expires_at)
    if not deadlines:
        return time.time()
    upper_bound = min(deadlines)
    if lower_bound < upper_bound:
        return lower_bound + ((upper_bound - lower_bound) / 2.0)
    return max(upper_bound - 0.000001, 0.000001)


def provider_availability_facts(
    provider: str,
    *,
    registered: bool,
    user_facing: bool,
    cli_available: bool,
) -> dict[str, object]:
    """Return the Rust facts shape for pure provider classification."""
    provider = require_provider_id(provider)
    if type(registered) is not bool:
        raise ValueError("registered must be a boolean")
    if type(user_facing) is not bool:
        raise ValueError("user_facing must be a boolean")
    if type(cli_available) is not bool:
        raise ValueError("cli_available must be a boolean")
    return {
        "provider": provider,
        "registered": registered,
        "user_facing": user_facing,
        "cli_available": cli_available,
    }


def classify_provider_availability(
    context: ProviderRoutingContext,
    facts: Mapping[str, object],
) -> ProviderAvailability:
    """Classify one provider from an immutable context and supplied facts."""
    binding = require_rust_binding("provider_availability_classify")
    payload: Any = binding(context.to_wire(), dict(facts))
    return ProviderAvailability.from_wire(payload)


def classify_provider_availability_many(
    context: ProviderRoutingContext,
    facts: Sequence[Mapping[str, object]],
) -> tuple[ProviderAvailability, ...]:
    """Classify many providers from one immutable context."""
    binding = require_rust_binding("provider_availability_classify_many")
    payload: Any = binding(context.to_wire(), [dict(item) for item in facts])
    if not isinstance(payload, list):
        raise ProviderPriorityStateError(
            "provider-availability batch result is not a list"
        )
    return tuple(ProviderAvailability.from_wire(item) for item in payload)


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


def provider_routing_context_route_key(
    context: ProviderRoutingContext,
) -> tuple[object, ...]:
    """Return a route-change key for actual disables and priority."""
    return (
        tuple(
            (
                provider,
                record.mode,
                record.created_at,
                record.expires_at,
                record.source,
            )
            for provider, record in sorted(context.provider_disables.items())
        ),
        provider_priority_route_key(context.priority),
        context.diagnostics,
    )


def _priority_or_none(payload: object) -> TemporaryProviderPriority | None:
    if payload is None:
        return None
    return TemporaryProviderPriority.from_wire(payload)


def _disable_or_none(payload: object) -> TemporaryProviderDisable | None:
    if payload is None:
        return None
    return TemporaryProviderDisable.from_wire(payload)


def _provider_disable_to_wire(record: TemporaryProviderDisable) -> dict[str, object]:
    created_at = (
        record.created_at
        if is_finite_number(record.created_at) and record.created_at > 0.0
        else 0.000001
    )
    return {
        "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        "provider": record.provider,
        "created_at": created_at,
        "expires_at": record.expires_at,
        "source": record.source,
        "mode": record.mode,
    }


def _provider_disables_to_wire(
    provider_disables: ProviderDisableSnapshot,
) -> list[dict[str, object]]:
    return [
        _provider_disable_to_wire(record)
        for _provider, record in sorted(provider_disables.items())
    ]


def _priority_to_wire(
    priority: TemporaryProviderPriority | None,
) -> dict[str, object] | None:
    return priority.to_wire() if priority is not None else None


def _priority_facts_to_wire(
    provider: str,
    facts: Mapping[str, object],
) -> dict[str, object]:
    required = {"provider", "registered", "user_facing", "cli_available"}
    if set(facts) != required:
        missing = sorted(required - set(facts))
        extra = sorted(set(facts) - required)
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise ValueError("invalid provider-priority facts: " + "; ".join(details))
    fact_provider = facts["provider"]
    if fact_provider != provider:
        raise ValueError(
            f"provider-priority facts are for {fact_provider!r}, not {provider!r}"
        )
    return provider_availability_facts(
        provider,
        registered=facts["registered"],  # type: ignore[arg-type]
        user_facing=facts["user_facing"],  # type: ignore[arg-type]
        cli_available=facts["cli_available"],  # type: ignore[arg-type]
    )


def _provenance_from_wire(
    payload: object,
) -> tuple[ProviderAvailabilityProvenance, ...]:
    if not isinstance(payload, list):
        raise ProviderPriorityStateError("provider provenance must be a list")
    values: list[ProviderAvailabilityProvenance] = []
    for item in payload:
        if item not in _PROVIDER_AVAILABILITY_PROVENANCE_VALUES:
            raise ProviderPriorityStateError(
                f"unsupported provider provenance: {item!r}"
            )
        values.append(item)
    if not values:
        raise ProviderPriorityStateError("provider provenance must be non-empty")
    return tuple(values)


def _diagnostics_from_wire(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise ProviderPriorityStateError("diagnostics must be a list of strings")
    return tuple(payload)


__all__ = [
    "PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION",
    "PROVIDER_PRIORITY_STATE_FILENAME",
    "PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION",
    "PROVIDER_ROUTING_CONTEXT_WIRE_SCHEMA_VERSION",
    "ProviderAvailability",
    "ProviderAvailabilityProvenance",
    "ProviderPriorityDecode",
    "ProviderPriorityStateError",
    "ProviderPriorityWriteOutcome",
    "ProviderPriorityWriteStatus",
    "ProviderRoutingContext",
    "TemporaryProviderPriority",
    "capture_provider_routing_context",
    "classify_provider_availability",
    "classify_provider_availability_many",
    "clear_provider_priority",
    "decode_provider_priority",
    "get_active_provider_priority",
    "provider_availability_facts",
    "provider_priority_route_key",
    "provider_priority_state_path",
    "provider_routing_context_from_parts",
    "provider_routing_context_route_key",
    "resolve_provider_routing_context",
    "set_provider_priority",
    "set_provider_priority_until",
]

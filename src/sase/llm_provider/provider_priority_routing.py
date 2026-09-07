"""Routing-context capture and provider availability classification."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
)
from .provider_priority_types import (
    ProviderPriorityStateError,
    TemporaryProviderPriority,
    provider_priority_route_key,
)

PROVIDER_ROUTING_CONTEXT_WIRE_SCHEMA_VERSION = 1
PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION = 1

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
            priority=_priority_record_or_none(payload["priority"]),
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
            priority=_priority_record_or_none(payload["priority"]),
            eligible_for_priority=eligible_for_priority,
        )


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
        None if priority is None else priority.to_wire(),
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


def _priority_record_or_none(payload: object) -> TemporaryProviderPriority | None:
    if payload is None:
        return None
    return TemporaryProviderPriority.from_wire(payload)


def _disable_or_none(payload: object) -> TemporaryProviderDisable | None:
    if payload is None:
        return None
    return TemporaryProviderDisable.from_wire(payload)


def _diagnostics_from_wire(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list) or not all(
        isinstance(item, str) for item in payload
    ):
        raise ProviderPriorityStateError("diagnostics must be a list of strings")
    return tuple(payload)


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

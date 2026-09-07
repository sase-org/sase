"""Rust-backed temporary LLM provider-priority facade.

Wire records, routing-context capture, and availability classification live in
sibling modules and are re-exported here to preserve the import and
monkeypatch surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

from .provider_disable import require_registered_provider
from .provider_priority_routing import (
    PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION as PROVIDER_AVAILABILITY_WIRE_SCHEMA_VERSION,
    PROVIDER_ROUTING_CONTEXT_WIRE_SCHEMA_VERSION as PROVIDER_ROUTING_CONTEXT_WIRE_SCHEMA_VERSION,
    ProviderAvailability as ProviderAvailability,
    ProviderAvailabilityProvenance as ProviderAvailabilityProvenance,
    ProviderDisableSnapshot as ProviderDisableSnapshot,
    ProviderRoutingContext as ProviderRoutingContext,
    capture_provider_routing_context as capture_provider_routing_context,
    classify_provider_availability as classify_provider_availability,
    classify_provider_availability_many as classify_provider_availability_many,
    provider_availability_facts as provider_availability_facts,
    provider_routing_context_from_parts as provider_routing_context_from_parts,
    provider_routing_context_route_key as provider_routing_context_route_key,
    resolve_provider_routing_context as resolve_provider_routing_context,
)
from .provider_priority_types import (
    PROVIDER_PRIORITY_DECODE_WIRE_SCHEMA_VERSION as PROVIDER_PRIORITY_DECODE_WIRE_SCHEMA_VERSION,
    PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION as PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
    PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION as PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION,
    ProviderPriorityDecode as ProviderPriorityDecode,
    ProviderPriorityStateError as ProviderPriorityStateError,
    ProviderPriorityWriteOutcome as ProviderPriorityWriteOutcome,
    ProviderPriorityWriteStatus as ProviderPriorityWriteStatus,
    TemporaryProviderPriority as TemporaryProviderPriority,
    provider_priority_route_key as provider_priority_route_key,
)

PROVIDER_PRIORITY_STATE_FILENAME = "llm_provider_priority.json"


def provider_priority_state_path() -> Path:
    """Return the canonical priority-state path under ``sase_home``."""
    return sase_home() / PROVIDER_PRIORITY_STATE_FILENAME


def get_active_provider_priority(
    now: float | None = None,
) -> TemporaryProviderPriority | None:
    """Return the active provider priority, self-cleaning stale state."""
    binding = require_rust_binding("provider_priority_get")
    payload: Any = binding(str(sase_home()), now)
    if payload is None:
        return None
    return TemporaryProviderPriority.from_wire(payload)


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
        None if expected is None else expected.to_wire(),
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
        None if expected is None else expected.to_wire(),
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
    payload: Any = binding(
        str(sase_home()),
        None if expected is None else expected.to_wire(),
        now,
    )
    return ProviderPriorityWriteOutcome.from_wire(payload)


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

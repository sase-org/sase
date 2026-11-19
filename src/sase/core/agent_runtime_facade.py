"""Thin Python facade for clan/agent-session wall-clock runtime aggregation."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from datetime import UTC, datetime
from collections.abc import Sequence
from typing import Any

from sase.core.agent_runtime_wire import ClanRuntimeMemberWire, ClanRuntimeWire
from sase.core.rust import require_rust_binding

# Serialized per-member wires, keyed by wire object identity. A per-second
# runtime tick rebuilds no member inputs for a stable clan: the aggregate
# layer above reuses its cached wire objects, so every member hits here
# and the tick only pays for the Rust aggregation itself (the displayed
# suffix, which is ``now``-dependent and must recompute). A changed member
# arrives as a new wire object, misses, and re-serializes. Entries hold a
# strong reference to their wire alongside the payload, so a garbage-collected
# wire's ``id()`` can never alias a live entry: the ``is`` check fails and
# the newcomer re-serializes. The Rust binding only reads the dicts (it
# extracts them into its own records), so sharing one payload across ticks
# is safe.
_SERIALIZED_WIRE_CACHE_MAX = 1024
_serialized_wire_cache: OrderedDict[
    int, tuple[ClanRuntimeMemberWire, dict[str, Any]]
] = OrderedDict()


def _serialized_member(member: ClanRuntimeMemberWire) -> dict[str, Any]:
    """Return the cached ``asdict()`` payload for one member wire."""
    key = id(member)
    hit = _serialized_wire_cache.get(key)
    if hit is not None and hit[0] is member:
        _serialized_wire_cache.move_to_end(key)
        return hit[1]
    payload = asdict(member)
    _serialized_wire_cache[key] = (member, payload)
    while len(_serialized_wire_cache) > _SERIALIZED_WIRE_CACHE_MAX:
        try:
            _serialized_wire_cache.popitem(last=False)
        except KeyError:
            break
    return payload


def aggregate_clan_runtime(
    members: Sequence[ClanRuntimeMemberWire],
    *,
    now: datetime | float | None = None,
) -> ClanRuntimeWire:
    """Return interval-union runtime with plan/question waits excised."""
    now_epoch_seconds = _now_epoch_seconds(now)
    rust_aggregate = require_rust_binding("aggregate_clan_runtime")
    payload: dict[str, Any] = rust_aggregate(
        [_serialized_member(member) for member in members],
        now_epoch_seconds,
    )
    return ClanRuntimeWire(
        wall_clock_seconds=float(payload.get("wall_clock_seconds", 0.0)),
        active=bool(payload.get("active", False)),
    )


def _now_epoch_seconds(value: datetime | float | None) -> float:
    if value is None:
        return datetime.now(UTC).timestamp()
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.timestamp()
    return float(value)


__all__ = ["aggregate_clan_runtime"]

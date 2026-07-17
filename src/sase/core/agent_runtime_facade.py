"""Thin Python facade for clan/family wall-clock runtime aggregation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from collections.abc import Sequence
from typing import Any

from sase.core.agent_runtime_wire import ClanRuntimeMemberWire, ClanRuntimeWire
from sase.core.rust import require_rust_binding


def aggregate_clan_runtime(
    members: Sequence[ClanRuntimeMemberWire],
    *,
    now: datetime | float | None = None,
) -> ClanRuntimeWire:
    """Return interval-union runtime with plan/question waits excised."""
    now_epoch_seconds = _now_epoch_seconds(now)
    rust_aggregate = require_rust_binding("aggregate_clan_runtime")
    payload: dict[str, Any] = rust_aggregate(
        [asdict(member) for member in members],
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

"""Per-member wire serialization cache in the clan runtime facade.

Phase ``ui_cpu_caches``: a per-second runtime tick must not re-serialize
every clan member. Unchanged members arrive as the same wire objects the
aggregate layer cached, so the facade reuses their payloads; only the
``now``-dependent aggregation (the displayed suffix) recomputes.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sase.core import agent_runtime_facade as facade_mod
from sase.core.agent_runtime_facade import aggregate_clan_runtime
from sase.core.agent_runtime_wire import ClanRuntimeMemberWire


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _clear_wire_cache() -> None:
    """Drop cached member payloads (test isolation)."""
    facade_mod._serialized_wire_cache.clear()


def _timestamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat()


def _running_members() -> list[ClanRuntimeMemberWire]:
    return [
        ClanRuntimeMemberWire(run_started_at=_timestamp(0)),
        ClanRuntimeMemberWire(
            run_started_at=_timestamp(10),
            plan_submitted_at=[_timestamp(20)],
            feedback_submitted_at=[_timestamp(30)],
        ),
    ]


def _capture_rust(monkeypatch: Any) -> tuple[list[list[dict[str, Any]]], Any]:
    """Capture per-call member payloads while delegating to the real binding."""
    real = facade_mod.require_rust_binding("aggregate_clan_runtime")
    seen: list[list[dict[str, Any]]] = []

    def _fake(members: Any, now_seconds: float) -> Any:
        seen.append(list(members))
        return real(members, now_seconds)

    monkeypatch.setattr(facade_mod, "require_rust_binding", lambda _name: _fake)
    return seen, real


def test_stable_members_reuse_serialized_payloads(
    monkeypatch: Any,
) -> None:
    _clear_wire_cache()
    seen, _real = _capture_rust(monkeypatch)
    members = _running_members()
    first = aggregate_clan_runtime(members, now=BASE + timedelta(seconds=60))
    second = aggregate_clan_runtime(members, now=BASE + timedelta(seconds=61))
    assert len(seen) == 2
    assert len(seen[0]) == len(seen[1]) == 2
    for before, after in zip(seen[0], seen[1], strict=True):
        assert after is before
        assert after == before
    assert second.wall_clock_seconds == first.wall_clock_seconds + 1
    assert second.active and first.active


def test_changed_member_reserializes_with_uncached_parity(
    monkeypatch: Any,
) -> None:
    _clear_wire_cache()
    seen, real = _capture_rust(monkeypatch)
    members = _running_members()
    aggregate_clan_runtime(members, now=BASE + timedelta(seconds=60))
    replacement = ClanRuntimeMemberWire(run_started_at=_timestamp(45))
    updated = [members[0], replacement]
    cached_result = aggregate_clan_runtime(updated, now=BASE + timedelta(seconds=61))

    assert len(seen) == 2
    assert seen[1][0] is seen[0][0]
    assert seen[1][1] is not seen[0][1]

    expected_payload = real(
        [asdict(member) for member in updated],
        (BASE + timedelta(seconds=61)).timestamp(),
    )
    assert cached_result.wall_clock_seconds == float(
        expected_payload.get("wall_clock_seconds", 0.0)
    )
    assert cached_result.active == bool(expected_payload.get("active", False))


def test_serialized_wire_cache_stays_bounded(monkeypatch: Any) -> None:
    _clear_wire_cache()
    monkeypatch.setattr(facade_mod, "_SERIALIZED_WIRE_CACHE_MAX", 4)
    try:
        wires = [ClanRuntimeMemberWire(run_started_at=_timestamp(i)) for i in range(10)]
        first = aggregate_clan_runtime(wires, now=BASE + timedelta(seconds=60))
        assert len(facade_mod._serialized_wire_cache) <= 4
        # Evicted wires still compute the same result on the next tick.
        second = aggregate_clan_runtime(wires, now=BASE + timedelta(seconds=61))
        assert second.wall_clock_seconds == first.wall_clock_seconds + 1
        assert len(facade_mod._serialized_wire_cache) <= 4
    finally:
        _clear_wire_cache()

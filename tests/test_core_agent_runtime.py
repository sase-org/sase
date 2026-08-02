"""Tests for the Rust-backed clan runtime facade."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.core.agent_runtime_facade import aggregate_clan_runtime
from sase.core.agent_runtime_wire import ClanRuntimeMemberWire, ClanRuntimeWire


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _timestamp(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat()


def test_facade_returns_interval_union_and_active_state() -> None:
    runtime = aggregate_clan_runtime(
        [
            ClanRuntimeMemberWire(
                run_started_at=_timestamp(0),
                stopped_at=_timestamp(20),
            ),
            ClanRuntimeMemberWire(
                run_started_at=_timestamp(10),
                stopped_at=_timestamp(30),
            ),
            ClanRuntimeMemberWire(run_started_at=_timestamp(40)),
        ],
        now=BASE + timedelta(seconds=50),
    )

    assert runtime == ClanRuntimeWire(wall_clock_seconds=40.0, active=True)


def test_facade_excludes_plan_and_pending_question_waits() -> None:
    runtime = aggregate_clan_runtime(
        [
            ClanRuntimeMemberWire(
                run_started_at=_timestamp(0),
                stopped_at=_timestamp(100),
                plan_submitted_at=[_timestamp(20)],
                feedback_submitted_at=[_timestamp(50)],
            ),
            ClanRuntimeMemberWire(
                run_started_at=_timestamp(110),
                questions_submitted_at=[_timestamp(130)],
                pending_question_submitted_at=_timestamp(130),
            ),
        ],
        now=BASE + timedelta(seconds=200),
    )

    assert runtime == ClanRuntimeWire(wall_clock_seconds=90.0, active=False)


def test_facade_does_not_use_synthesized_terminal_timestamp() -> None:
    runtime = aggregate_clan_runtime(
        [
            ClanRuntimeMemberWire(
                run_started_at=_timestamp(0),
                finished_at=(BASE + timedelta(hours=40)).timestamp(),
                has_done_marker=True,
                terminal_is_synthesized=True,
            )
        ],
        now=BASE + timedelta(hours=41),
    )

    assert runtime == ClanRuntimeWire()

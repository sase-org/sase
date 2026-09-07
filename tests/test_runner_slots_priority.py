"""Unit tests for runner-slot wait-priority and deference primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    better_priority_agent_pending,
    deference_satisfied,
    deference_window_seconds,
    normalize_wait_priority,
)
from tests._runner_slots_helpers import _record


def test_normalize_wait_priority_defaults_missing_and_invalid_values() -> None:
    assert normalize_wait_priority(3) == 3
    assert normalize_wait_priority(None) == DEFAULT_WAIT_PRIORITY
    assert normalize_wait_priority(True) == DEFAULT_WAIT_PRIORITY
    assert normalize_wait_priority(-1) == DEFAULT_WAIT_PRIORITY
    assert normalize_wait_priority("3") == DEFAULT_WAIT_PRIORITY


def test_deference_window_scales_only_worse_priorities_and_clamps() -> None:
    assert deference_window_seconds(1, seconds_per_step=3, max_seconds=60) == 0.0
    assert (
        deference_window_seconds(
            DEFAULT_WAIT_PRIORITY,
            seconds_per_step=3,
            max_seconds=60,
        )
        == 0.0
    )
    assert deference_window_seconds(12, seconds_per_step=3, max_seconds=60) == 6.0
    assert deference_window_seconds(40, seconds_per_step=3, max_seconds=60) == 60.0


def test_deference_satisfied_requires_valid_elapsed_timestamp() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    assert deference_satisfied(None, now, 0)
    assert not deference_satisfied(None, now, 30)
    assert not deference_satisfied("not-a-time", now, 30)
    assert not deference_satisfied((now + timedelta(seconds=1)).isoformat(), now, 30)
    assert not deference_satisfied(
        (now - timedelta(seconds=29)).isoformat(),
        now,
        30,
    )
    assert deference_satisfied(
        (now - timedelta(seconds=30)).isoformat(),
        now,
        30,
    )


def test_better_priority_agent_pending_finds_only_plausible_arrivals() -> None:
    me = "/me"
    candidate = _record("/candidate", meta_wait_priority=2)

    assert better_priority_agent_pending(
        [candidate],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [candidate],
        lambda _record: False,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/started", run_started=True, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [
            _record(
                "/parked",
                requested_at="2026-07-25T12:00:00+00:00",
                meta_wait_priority=2,
            )
        ],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/done", done=True, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/step", appears_as_agent=False, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/equal", meta_wait_priority=20)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/worse", meta_wait_priority=30)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record(me, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )

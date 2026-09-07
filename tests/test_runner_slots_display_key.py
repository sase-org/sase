"""Unit tests for the runner-slot queue display sort key."""

from __future__ import annotations

from datetime import datetime

from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    runner_slot_queue_display_key,
    runner_slot_waiter_sort_key,
)


def _display_key(
    name: str,
    *,
    running_count: int,
    threshold: int | None,
    priority: int | None = None,
    requested_at: str = "2026-07-12T12:00:00+00:00",
) -> tuple[int, int, int, int, datetime, str, str]:
    return runner_slot_queue_display_key(
        running_count=running_count,
        threshold=threshold,
        priority=priority,
        slot_requested_at=requested_at,
        timestamp=name,
        artifact_dir=f"/{name}",
    )


def test_display_key_places_parked_waiter_after_admissible_waiter() -> None:
    ordered = sorted(
        ("drain", "default"),
        key=lambda name: _display_key(
            name,
            running_count=1,
            threshold=0 if name == "drain" else 9,
            priority=1 if name == "drain" else 20,
        ),
    )

    assert ordered == ["default", "drain"]


def test_display_key_orders_parked_waiters_by_threshold_descending() -> None:
    ordered = sorted(
        ("deep", "near"),
        key=lambda name: _display_key(
            name,
            running_count=5,
            threshold=0 if name == "deep" else 4,
            requested_at="2026-07-12T12:00:00+00:00",
        ),
    )

    assert ordered == ["near", "deep"]


def test_display_key_keeps_priority_then_fifo_for_admissible_waiters() -> None:
    ordered = sorted(
        ("older-default", "newer-urgent", "newer-default"),
        key=lambda name: _display_key(
            name,
            running_count=1,
            threshold=9,
            priority=1 if name == "newer-urgent" else DEFAULT_WAIT_PRIORITY,
            requested_at=(
                "2026-07-12T12:00:00+00:00"
                if name == "older-default"
                else "2026-07-12T12:00:01+00:00"
            ),
        ),
    )

    assert ordered == ["newer-urgent", "older-default", "newer-default"]


def test_display_key_treats_missing_threshold_as_zero() -> None:
    missing = _display_key("waiter", running_count=1, threshold=None)
    explicit_zero = _display_key("waiter", running_count=1, threshold=0)

    assert missing == explicit_zero


def test_display_key_degrades_to_admission_key_at_zero_running_count() -> None:
    display = runner_slot_queue_display_key(
        running_count=0,
        threshold=0,
        priority=1,
        slot_requested_at="2026-07-12T12:00:00+00:00",
        timestamp="1",
        artifact_dir="/drain",
    )
    admission = runner_slot_waiter_sort_key(
        priority=1,
        slot_requested_at="2026-07-12T12:00:00+00:00",
        timestamp="1",
        artifact_dir="/drain",
    )

    assert display[:2] == (0, 0)
    assert display[2:] == admission

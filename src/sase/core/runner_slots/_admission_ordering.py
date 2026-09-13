"""Priority/FIFO ordering keys and deference-window math for slot waiters."""

from __future__ import annotations

from datetime import UTC, datetime

from ._admission_types import DEFAULT_QUEUE_WEIGHT, DEFAULT_WAIT_PRIORITY


def normalize_wait_priority(value: object) -> int:
    """Return a valid queue priority, defaulting invalid marker values."""
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_WAIT_PRIORITY


def runner_slot_waiter_sort_key(
    *,
    priority: object,
    slot_requested_at: str | None,
    timestamp: str | None,
    artifact_dir: str | None,
) -> tuple[int, int, datetime, str, str]:
    """Return the canonical priority/FIFO ordering key for one slot waiter."""
    requested_at = slot_requested_at or ""
    try:
        parsed = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        invalid = 0
    except ValueError:
        parsed = datetime.max.replace(tzinfo=UTC)
        invalid = 1
    return (
        normalize_wait_priority(priority),
        invalid,
        parsed,
        timestamp or "",
        artifact_dir or "",
    )


def runner_slot_queue_display_key(
    *,
    running_count: int,
    threshold: int | None,
    requested_weight: float = DEFAULT_QUEUE_WEIGHT,
    priority: object,
    slot_requested_at: str | None,
    timestamp: str | None,
    artifact_dir: str | None,
) -> tuple[int, int, int, int, datetime, str, str]:
    """Return the capacity-aware presentation key for one slot waiter."""
    admission_limit = float(threshold if threshold is not None else 0)
    parked = float(running_count) + float(requested_weight) > admission_limit
    return (
        1 if parked else 0,
        -int(admission_limit) if parked else 0,
        *runner_slot_waiter_sort_key(
            priority=priority,
            slot_requested_at=slot_requested_at,
            timestamp=timestamp,
            artifact_dir=artifact_dir,
        ),
    )


def deference_window_seconds(
    priority: int,
    *,
    seconds_per_step: int,
    max_seconds: int,
) -> float:
    """Return the bounded admission delay for a deprioritized waiter."""
    if priority <= DEFAULT_WAIT_PRIORITY:
        return 0.0
    return float(
        min(
            (priority - DEFAULT_WAIT_PRIORITY) * seconds_per_step,
            max_seconds,
        )
    )


def deference_satisfied(
    eligible_since: str | None,
    now: datetime,
    window_seconds: float,
) -> bool:
    """Return whether continuous eligibility has lasted for the full window."""
    if window_seconds <= 0:
        return True
    if not eligible_since:
        return False
    try:
        started = datetime.fromisoformat(eligible_since.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    else:
        started = started.astimezone(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    elapsed = (now - started).total_seconds()
    return elapsed >= 0 and elapsed >= window_seconds

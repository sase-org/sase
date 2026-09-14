"""Runner-slot marker state: priority, queue weight, and eligibility parsing.

These helpers reconcile a waiting-marker's persisted fields with a launch
directive's explicit overrides into the priority, queue-weight, and
continuous-eligibility values ``_try_claim_runner_slot`` uses to decide
admission.
"""

import math
from datetime import UTC, datetime
from typing import Any

from sase.core.runner_slots import DEFAULT_WAIT_PRIORITY


class _RunnerSlotAdmissionError(RuntimeError):
    """Raised when a serial continuation requests an incompatible live claim."""


def _invalid_queue_weight_error(
    source: str, value: object
) -> _RunnerSlotAdmissionError:
    return _RunnerSlotAdmissionError(
        f"Invalid queue_weight in {source}: expected a positive finite number, "
        f"got {value!r}."
    )


def _marker_runner_condition_state(
    waiting_data: dict[str, Any] | None,
    directive_threshold: int | None,
) -> tuple[int | None, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        explicit = (
            waiting_data.get("queue_capacity_explicit") is True
            or waiting_data.get("wait_runners_explicit") is True
        )
        marker_value = waiting_data.get(
            "queue_capacity",
            waiting_data.get("wait_runners"),
        )
        if explicit and type(marker_value) is int and marker_value >= 0:
            return marker_value, True
    if directive_threshold is not None:
        return directive_threshold, True
    return None, False


def _legacy_marker_priority_explicit(waiting_data: dict[str, Any]) -> bool:
    marker_value = waiting_data.get("wait_priority")
    # Legacy markers had no explicitness flag. A non-default priority almost
    # certainly came from a user directive or edit; the default was often written
    # implicitly by the runner and must not shadow later directive metadata.
    return (
        "wait_priority_explicit" not in waiting_data
        and type(marker_value) is int
        and marker_value >= 0
        and marker_value != DEFAULT_WAIT_PRIORITY
    )


def _marker_priority_state(
    waiting_data: dict[str, Any] | None,
    directive_priority: int | None,
) -> tuple[int, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        marker_value = waiting_data.get("wait_priority")
        marker_explicit = waiting_data.get(
            "wait_priority_explicit"
        ) is True or _legacy_marker_priority_explicit(waiting_data)
        if marker_explicit and type(marker_value) is int and marker_value >= 0:
            return marker_value, True
    if type(directive_priority) is int and directive_priority >= 0:
        return directive_priority, True
    return DEFAULT_WAIT_PRIORITY, False


def _valid_queue_weight(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight) or weight <= 0:
        return None
    return weight


def _marker_queue_weight_state(
    waiting_data: dict[str, Any] | None,
    directive_weight: float,
    directive_explicit: bool,
) -> tuple[float, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        if waiting_data.get("queue_weight_invalid") is True:
            raise _invalid_queue_weight_error(
                "waiting marker",
                waiting_data.get("queue_weight"),
            )
        if "queue_weight" in waiting_data:
            marker_weight = _valid_queue_weight(waiting_data.get("queue_weight"))
            if marker_weight is None:
                raise _invalid_queue_weight_error(
                    "waiting marker",
                    waiting_data.get("queue_weight"),
                )
            return marker_weight, waiting_data.get("queue_weight_explicit") is True
    weight = _valid_queue_weight(directive_weight)
    if weight is None:
        raise _invalid_queue_weight_error("agent metadata", directive_weight)
    return weight, directive_explicit


def _continuous_eligibility_start(
    eligible_since: object,
    now: datetime,
) -> tuple[str, bool]:
    """Return a valid non-future start and whether it had to be reset."""
    if isinstance(eligible_since, str) and eligible_since:
        try:
            started = datetime.fromisoformat(eligible_since.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            else:
                started = started.astimezone(UTC)
            normalized_now = (
                now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
            )
            if started <= normalized_now:
                return eligible_since, False
    return now.isoformat(), True

"""Shared queue-weight validation and successor-inheritance rules.

Explicit ``0.0`` is a valid non-occupying weight. Implicit zero stays
invalid, matching the Rust record/marker/fleet helpers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

QUEUE_WEIGHT_ERROR = (
    "queue_weight must be a non-negative finite number; "
    "0 is valid only when queue_weight_explicit is true"
)
MONITOR_QUEUE_WEIGHT_OVERRIDDEN_KEY = "monitor_queue_weight_overridden"
MONITOR_INHERITED_QUEUE_WEIGHT_KEY = "monitor_inherited_queue_weight"
MONITOR_INHERITED_QUEUE_WEIGHT_EXPLICIT_KEY = "monitor_inherited_queue_weight_explicit"


def valid_queue_weight(value: object, *, explicit: bool) -> float | None:
    """Return a finite queue weight, accepting ``0.0`` only when *explicit*."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight):
        return None
    if weight == 0.0:
        return 0.0 if explicit else None
    if weight < 0.0:
        return None
    return weight


def inheritable_queue_weight(meta: Mapping[str, Any]) -> tuple[float | None, bool]:
    """Return the weight and explicitness a successor should inherit.

    User-authored explicit ``0.0`` stays ``(0.0, True)``. A positive weight
    is inherited implicitly so lineage claim reuse still works. A host
    ``queue_weight_override`` (the epic-launch monitor's quiet zero) is not
    inherited: successors receive the pre-override values, or ``(None, False)``
    when the starter had no weight.
    """
    if meta.get(MONITOR_QUEUE_WEIGHT_OVERRIDDEN_KEY) is True:
        if MONITOR_INHERITED_QUEUE_WEIGHT_KEY not in meta:
            return None, False
        return _inheritable_from_stored(
            meta.get(MONITOR_INHERITED_QUEUE_WEIGHT_KEY),
            meta.get(MONITOR_INHERITED_QUEUE_WEIGHT_EXPLICIT_KEY) is True,
        )
    if meta.get("queue_weight_invalid") is True:
        return None, False
    if "queue_weight" not in meta:
        return None, False
    return _inheritable_from_stored(
        meta.get("queue_weight"),
        meta.get("queue_weight_explicit") is True,
    )


def _inheritable_from_stored(
    value: object, explicit: bool
) -> tuple[float | None, bool]:
    weight = valid_queue_weight(value, explicit=explicit)
    if weight is None:
        return None, False
    if weight == 0.0:
        return 0.0, True
    return weight, False

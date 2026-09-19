"""Fleet row status and queue normalization helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ._fleet_agents_scalars import float_or_none, optional_str

_LIVENESS_STOPPED_VALUES = frozenset({"dead", "not_process"})


def queue_weight(summary: Mapping[str, Any]) -> float | None:
    weight = float_or_none(summary.get("queue_weight"))
    if weight is None or not math.isfinite(weight):
        return None
    if weight == 0.0:
        return 0.0 if summary.get("queue_weight_explicit") is True else None
    if weight <= 0.0:
        return None
    return weight


def status_from_summary(
    summary: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    liveness: Mapping[str, Any],
    attention: Mapping[str, Any] | None = None,
    *,
    lifecycle_token: object = None,
    liveness_token: object = None,
) -> str:
    # A correlated, still-pending attention entry is the most specific
    # signal available: it distinguishes a question from a gate the way a
    # bare lifecycle/needs_attention flag never can.
    if attention is not None and attention.get("state") == "pending":
        kind = attention.get("kind")
        if kind == "question":
            return "QUESTION"
        if kind == "gate":
            return "WAITING INPUT"
    value = optional_str(
        summary.get("status"),
        lifecycle_token if isinstance(lifecycle_token, str) else None,
        lifecycle.get("display_status"),
        lifecycle.get("status"),
        lifecycle.get("state"),
        liveness_token if isinstance(liveness_token, str) else None,
        liveness.get("status"),
        liveness.get("state"),
    )
    dead = liveness_is_stopped(liveness_token, liveness)
    if not value:
        return "WAS RUNNING" if dead else "RUNNING"
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    status_map = {
        "active": "RUNNING",
        "alive": "RUNNING",
        "running": "RUNNING",
        "started": "RUNNING",
        "queued": "QUEUED",
        "pending": "QUEUED",
        "waiting": "WAITING",
        "waiting_input": "WAITING INPUT",
        "needs_input": "WAITING INPUT",
        "blocked": "WAITING INPUT",
        # No row-scoped attention entry has arrived; fall back to the generic
        # remote-blocked status the owner's lifecycle/needs_attention signal
        # implies.
        "asking": "WAITING INPUT",
        "failed": "FAILED",
        "error": "FAILED",
        "done": "DONE",
        "complete": "DONE",
        "completed": "DONE",
        "terminal": "DONE",
        "stopped": "STOPPED",
        "cancelled": "STOPPED",
        "canceled": "STOPPED",
        "starting": "STARTING",
    }
    if normalized not in status_map and bool(summary.get("needs_attention")):
        return "WAITING INPUT"
    resolved = status_map.get(normalized, value.strip())
    # Owner-resolved liveness overrides a stale RUNNING/STARTING claim: the
    # process is confirmed gone, so the row presents "was running" instead
    # of fabricating an active state. Never demote other statuses (a real
    # completion, failure, or pending-input pause stays as reported).
    if dead and resolved in {"RUNNING", "STARTING"}:
        return "WAS RUNNING"
    return resolved


def liveness_is_stopped(liveness_token: object, liveness: Mapping[str, Any]) -> bool:
    """Whether owner-resolved liveness definitively rules out an active row.

    Mirrors sase-core's ``bucket_for_lifecycle`` liveness_stops predicate:
    only a definitively Dead/NotProcess liveness may demote a row. Alive or
    genuinely Unknown liveness never hides a potentially live agent.
    """
    value = optional_str(
        liveness_token if isinstance(liveness_token, str) else None,
        liveness.get("liveness"),
        liveness.get("status"),
        liveness.get("state"),
    )
    if not value:
        return False
    return value.casefold() in _LIVENESS_STOPPED_VALUES


_FLEET_STATUS_BUCKET_WIRE_MAP: dict[str, str] = {
    "stopped": "Stopped",
    "failed": "Failed",
    "starting": "Starting",
    "running": "Running",
    "queued": "Queued",
    "waiting": "Waiting",
    "done": "Done",
}


def status_bucket_from_wire(value: object) -> str | None:
    """Map the wire's liveness-aware ``status_bucket`` to a display bucket.

    The wire enum is a deliberate 1:1 mirror of
    ``sase.agent.status_buckets.AGENT_STATUS_BUCKETS``, so setting
    ``Agent.status_bucket`` from it overrides the local text-derived bucket
    fallback everywhere that already consults ``agent_status_bucket()``
    (banners, folding, filters) with the owner's liveness-aware bucket.
    """
    if not isinstance(value, str):
        return None
    return _FLEET_STATUS_BUCKET_WIRE_MAP.get(value.casefold())


__all__ = [
    "liveness_is_stopped",
    "queue_weight",
    "status_bucket_from_wire",
    "status_from_summary",
]

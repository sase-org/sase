"""Shared helpers for trusted BeadStaleCleanup gate tests."""

from __future__ import annotations

from typing import Any

from sase.bead._stale_cleanup_gate_spec import build_bead_stale_cleanup_gate_spec

DEFAULT_STALE_AS_OF = "2026-08-17T11:00:00-04:00"


def stale_cleanup_bead(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": "sase",
        "bead_id": "sase-task.1",
        "title": "Follow up on cache invalidation",
        "created_at": "2026-08-01T09:14:02-04:00",
        "plus_one_count": 0,
        "size": "small",
    }
    fields.update(overrides)
    return fields


def stale_cleanup_spec(
    *, request_id: str = "bead-stale-cleanup-1", **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "beads": [stale_cleanup_bead()],
        "omitted_count": 0,
        "min_plus_ones": 1,
        "stale_after_days": 7,
        "stale_cleanup_min_beads": 10,
        "stale_as_of": DEFAULT_STALE_AS_OF,
        "producer": {"chop": "bead_stale_cleanup"},
    }
    fields.update(overrides)
    return build_bead_stale_cleanup_gate_spec(**fields)

"""Rust-backed Focus/Fleet running-count calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def count_focus_and_fleet_from_federation(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Return Focus/Fleet counts from raw federation worker read results."""
    payload = require_rust_binding("fleet_count_focus_and_fleet_from_federation")(
        dict(request)
    )
    if not isinstance(payload, dict):
        raise TypeError(
            "fleet_count_focus_and_fleet_from_federation returned a non-object payload"
        )
    return payload


__all__ = ["count_focus_and_fleet_from_federation"]

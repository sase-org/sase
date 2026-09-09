"""Rust-backed Focus/Fleet running-count calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def count_focus_and_fleet(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return shared Focus and Fleet count projections."""
    payload = require_rust_binding("fleet_count_focus_and_fleet")(dict(request))
    if not isinstance(payload, dict):
        raise TypeError("fleet_count_focus_and_fleet returned a non-object payload")
    return payload


__all__ = ["count_focus_and_fleet"]

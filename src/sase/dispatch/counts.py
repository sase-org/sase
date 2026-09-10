"""Rust-backed local/remote running-count calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def count_focus_and_fleet(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return shared local and remote count projections."""
    payload = require_rust_binding("fleet_count_focus_and_fleet")(dict(request))
    if not isinstance(payload, dict):
        raise TypeError("fleet_count_focus_and_fleet returned a non-object payload")
    return payload


def normalize_fleet_federation_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Return the core-normalized federation read response."""
    payload = require_rust_binding("fleet_normalize_federation_response")(
        {"schema_version": 1, "response": dict(response)}
    )
    if not isinstance(payload, dict):
        raise TypeError(
            "fleet_normalize_federation_response returned a non-object payload"
        )
    return payload


def count_focus_and_fleet_from_federation(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Return shared local and remote counts from raw federation envelopes."""
    payload = require_rust_binding("fleet_count_focus_and_fleet_from_federation")(
        dict(request)
    )
    if not isinstance(payload, dict):
        raise TypeError(
            "fleet_count_focus_and_fleet_from_federation returned a non-object payload"
        )
    return payload


__all__ = [
    "count_focus_and_fleet",
    "count_focus_and_fleet_from_federation",
    "normalize_fleet_federation_response",
]

"""Rust-backed stop-before-removal decision for forced name reuse."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sase.core.rust import require_rust_binding

FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION = 1


def decide_force_reuse_stop_barrier(
    targets: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return Rust's decision for a concrete forced-reuse stop batch."""
    version_binding = require_rust_binding(
        "force_reuse_stop_barrier_wire_schema_version"
    )
    version = int(version_binding())
    if version != FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION:
        raise AttributeError(
            "sase_core_rs force-reuse stop barrier wire is stale: "
            f"expected {FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION}, got {version}"
        )
    binding = require_rust_binding("decide_force_reuse_stop_barrier")
    request = {
        "schema_version": FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION,
        "targets": [dict(target) for target in targets],
    }
    result = binding(request)
    if not isinstance(result, dict):
        raise TypeError("sase_core_rs returned a non-dict stop barrier decision")
    schema = result.get("schema_version")
    if schema != FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION:
        raise ValueError(
            "sase_core_rs returned an incompatible stop barrier decision: "
            f"schema_version must be {FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION}"
        )
    return result


__all__ = [
    "FORCE_REUSE_STOP_BARRIER_WIRE_SCHEMA_VERSION",
    "decide_force_reuse_stop_barrier",
]

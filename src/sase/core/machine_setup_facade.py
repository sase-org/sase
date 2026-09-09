"""Typed Python facade for Tailnet discovery and enrollment reconciliation."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sase.core.rust import require_rust_binding


@lru_cache(maxsize=1)
def _machine_setup_wire_schema_version() -> int:
    binding = require_rust_binding("machine_setup_wire_schema_version")
    return int(binding())


def classify_tailnet_health(request: dict[str, Any]) -> dict[str, Any]:
    """Classify one health payload or host-collected probe error."""
    return _call_machine_setup("classify_tailnet_health", request, "tailnet health")


def classify_tailnet_discovery(request: dict[str, Any]) -> dict[str, Any]:
    """Parse Tailscale status JSON and assemble candidates from observations."""
    return _call_machine_setup(
        "classify_tailnet_discovery",
        request,
        "tailnet discovery",
    )


def reconcile_machine_enrollments(request: dict[str, Any]) -> dict[str, Any]:
    """Classify discovery candidates against enrolled pins."""
    return _call_machine_setup(
        "reconcile_machine_enrollments",
        request,
        "machine enrollment reconcile",
    )


def _call_machine_setup(
    name: str, request: dict[str, Any], label: str
) -> dict[str, Any]:
    binding = require_rust_binding(name)
    payload = dict(binding(_with_schema(request)))
    actual = payload.get("schema_version")
    expected = _machine_setup_wire_schema_version()
    if actual != expected:
        raise ValueError(
            f"{label} wire schema mismatch: got {actual!r}, expected {expected}"
        )
    return payload


def _with_schema(request: dict[str, Any]) -> dict[str, Any]:
    payload = dict(request)
    payload.setdefault("schema_version", _machine_setup_wire_schema_version())
    return payload


__all__ = [
    "classify_tailnet_discovery",
    "classify_tailnet_health",
    "reconcile_machine_enrollments",
]

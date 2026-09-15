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


def assess_machine_init_review(request: dict[str, Any]) -> dict[str, Any]:
    """Decide whether onboarding has unreviewed new machine candidates."""
    return _call_machine_setup(
        "assess_machine_init_review",
        request,
        "machine init review assessment",
    )


def merge_machine_init_review(request: dict[str, Any]) -> dict[str, Any]:
    """Merge candidates from a completed explicit machine-init review."""
    return _call_machine_setup(
        "merge_machine_init_review",
        request,
        "machine init review merge",
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
    "assess_machine_init_review",
    "classify_tailnet_discovery",
    "classify_tailnet_health",
    "merge_machine_init_review",
    "reconcile_machine_enrollments",
]

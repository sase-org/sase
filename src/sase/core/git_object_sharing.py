"""Schema-checked facade for Rust-owned Git object-sharing policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION = 3
"""Must match ``sase_core::git_object_sharing``."""

# Every install/remove plan names the context it mutates from, and the core
# picks the safety guards it enforces from that name. ``classify`` is the only
# operation that may omit one.
MUTATION_CONTEXT_NEW_CHECKOUT = "new_checkout"
MUTATION_CONTEXT_EXISTING_REUSE = "existing_reuse"
MUTATION_CONTEXT_MAINTENANCE_REPAIR = "maintenance_repair"
MUTATION_CONTEXT_MAINTENANCE_COMPACT = "maintenance_compact"
MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE = "maintenance_dissociate"

# Freshly observed claim/occupant state. The maintenance contexts mutate only
# when the caller proves both are ``clear``; "positive" and "could not look"
# both fail the plan closed, so an unobservable caller never gets a mutation.
OBSERVATION_CLEAR = "clear"
OBSERVATION_PRESENT = "present"
OBSERVATION_UNAVAILABLE = "unavailable"


def plan_git_object_sharing(request: Mapping[str, Any]) -> dict[str, Any]:
    """Plan alternates classification or mutation through ``sase_core_rs``."""
    _require_wire_schema()
    payload = dict(request)
    payload["schema_version"] = GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("plan_git_object_sharing")
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned an invalid git-object-sharing plan")
    if raw.get("schema_version") != GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible git-object-sharing plan: "
            f"schema_version must be {GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION}"
        )
    return raw


def _require_wire_schema() -> None:
    binding = require_rust_binding("git_object_sharing_wire_schema_version")
    version = int(binding())
    if version != GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs git-object-sharing wire is stale: expected "
            f"{GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION}, got {version}"
        )


__all__ = [
    "GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION",
    "MUTATION_CONTEXT_EXISTING_REUSE",
    "MUTATION_CONTEXT_MAINTENANCE_COMPACT",
    "MUTATION_CONTEXT_MAINTENANCE_DISSOCIATE",
    "MUTATION_CONTEXT_MAINTENANCE_REPAIR",
    "MUTATION_CONTEXT_NEW_CHECKOUT",
    "OBSERVATION_CLEAR",
    "OBSERVATION_PRESENT",
    "OBSERVATION_UNAVAILABLE",
    "plan_git_object_sharing",
]

"""Schema-checked facade for Rust-owned Git object-sharing policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

GIT_OBJECT_SHARING_WIRE_SCHEMA_VERSION = 1
"""Must match ``sase_core::git_object_sharing``."""


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
    "plan_git_object_sharing",
]

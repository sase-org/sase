"""Thin adapter over the Rust workspace-retention policy.

The Rust core owns classification and identity matching. Python gathers
claim, successor, dirt, and probe facts and applies the selected effect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

#: Mirrors Rust ``WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION``.
WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION = 1

DISPOSITION_RETAIN = "retain"
DISPOSITION_RELEASE = "release"
DISPOSITION_OWNERSHIP_MOVED = "ownership_moved"


def wire_schema_version() -> int:
    """Return the Rust workspace-retention wire schema version."""
    binding = require_rust_binding("workspace_retention_wire_schema_version")
    return int(binding())


def decide_workspace_retention(request: Mapping[str, Any]) -> dict[str, Any]:
    """Classify whether a settling owner should retain, release, or stand down."""
    binding = require_rust_binding("decide_workspace_retention")
    return dict(binding(dict(request)))


__all__ = [
    "DISPOSITION_OWNERSHIP_MOVED",
    "DISPOSITION_RELEASE",
    "DISPOSITION_RETAIN",
    "WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION",
    "decide_workspace_retention",
    "wire_schema_version",
]

"""Python facade over the Rust bead-action policy bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

BEAD_ACTION_WIRE_SCHEMA_VERSION = 1


def bead_action_wire_schema_version() -> int:
    binding = require_rust_binding("bead_action_wire_schema_version")
    return int(binding())


def parse_bead_action_field(payload: Mapping[str, Any]) -> str | None:
    """Return explicit ``bead_action`` from *payload*, preserving omission."""

    binding = require_rust_binding("parse_bead_action_field")
    result = binding(dict(payload))
    if result is None:
        return None
    return str(result)


def decide_bead_action(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the Rust policy disposition for one stitch/commit fact set."""

    binding = require_rust_binding("decide_bead_action")
    result = binding(dict(request))
    if not isinstance(result, dict):
        raise TypeError("decide_bead_action returned a non-mapping")
    return dict(result)


__all__ = [
    "BEAD_ACTION_WIRE_SCHEMA_VERSION",
    "bead_action_wire_schema_version",
    "decide_bead_action",
    "parse_bead_action_field",
]

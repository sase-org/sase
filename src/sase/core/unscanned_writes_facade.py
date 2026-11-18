"""Python facade over the Rust unscanned-write policy bindings."""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding

UNSCANNED_WIRE_SCHEMA_VERSION = 1


def unscanned_wire_schema_version() -> int:
    binding = require_rust_binding("unscanned_wire_schema_version")
    return int(binding())


def select_unscanned_coverage(request: dict[str, Any]) -> dict[str, Any]:
    binding = require_rust_binding("select_unscanned_coverage")
    result = binding(request)
    if not isinstance(result, dict):
        raise ValueError("select_unscanned_coverage returned non-dict")
    return result


def suggest_unscanned_repair(request: dict[str, Any]) -> dict[str, Any]:
    binding = require_rust_binding("suggest_unscanned_repair")
    result = binding(request)
    if not isinstance(result, dict):
        raise ValueError("suggest_unscanned_repair returned non-dict")
    return result


__all__ = [
    "UNSCANNED_WIRE_SCHEMA_VERSION",
    "select_unscanned_coverage",
    "suggest_unscanned_repair",
    "unscanned_wire_schema_version",
]

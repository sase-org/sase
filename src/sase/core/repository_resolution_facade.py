"""Facade for canonical repository-open identity resolution."""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding


def repository_resolution_wire_schema_version() -> int:
    """Return the repository-resolution wire schema version."""
    binding = require_rust_binding("repository_resolution_wire_schema_version")
    return int(binding())


def canonical_repository_identity(value: str) -> dict[str, Any] | None:
    """Canonicalize a supported repository identity via ``sase_core_rs``."""
    binding = require_rust_binding("canonical_repository_identity")
    payload: dict[str, Any] | None = binding(value)
    return payload


def resolve_repository_reference(request: dict[str, Any]) -> dict[str, Any]:
    """Resolve a requested repo ref against configured candidates via Rust."""
    binding = require_rust_binding("resolve_repository_reference")
    payload: dict[str, Any] = binding(request)
    return payload


__all__ = [
    "canonical_repository_identity",
    "repository_resolution_wire_schema_version",
    "resolve_repository_reference",
]

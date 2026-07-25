"""Typed Python facade for shared commit-SHA equivalence."""

from __future__ import annotations

from sase.core.rust import require_rust_binding


def commit_shas_equivalent(left: str, right: str) -> bool:
    """Return whether two valid SHAs identify the same commit."""
    binding = require_rust_binding("commit_shas_equivalent")
    return bool(binding(left, right))

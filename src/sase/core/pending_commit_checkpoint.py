"""Typed Python facade for pending commit-checkpoint recovery."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sase.core.rust import require_rust_binding


@lru_cache(maxsize=1)
def _pending_commit_checkpoint_wire_schema_version() -> int:
    binding = require_rust_binding("pending_commit_checkpoint_wire_schema_version")
    return int(binding())


def decide_pending_commit_checkpoint_recovery(
    request: dict[str, Any],
) -> dict[str, Any]:
    binding = require_rust_binding("decide_pending_commit_checkpoint_recovery")
    payload = dict(binding(request))
    expected = _pending_commit_checkpoint_wire_schema_version()
    actual = payload.get("schema_version")
    if actual != expected:
        raise ValueError(
            "pending commit checkpoint wire schema mismatch: "
            f"got {actual!r}, expected {expected}"
        )
    return payload


__all__ = [
    "decide_pending_commit_checkpoint_recovery",
]

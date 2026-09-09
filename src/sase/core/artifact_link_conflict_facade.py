"""Python facade for Rust-backed artifact-link conflict helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def merge_artifact_link_indexes(
    base: Mapping[str, Any],
    ours: Mapping[str, Any],
    theirs: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge three schema-v2 per-artifact link indexes through sase-core."""

    binding = require_rust_binding("artifact_link_merge_indexes")
    return dict(binding(dict(base), dict(ours), dict(theirs)))


__all__ = ["merge_artifact_link_indexes"]

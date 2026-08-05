"""Python facade for Rust-backed bead event conflict helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_bead_store_write_sandboxed


def merge_event_streams_with_relocation(
    base: dict[str, Any],
    ours: dict[str, Any],
    theirs: dict[str, Any],
    relocation_issue_id: str | None = None,
) -> dict[str, Any]:
    """Merge one stream, renumbering a concurrently minted duplicate bead id.

    Wheels older than the relocation binding fall back to the plain merge,
    which reproduces the historical duplicate-creation error instead of
    silently dropping one side of the collision.
    """
    try:
        binding = require_rust_binding("bead_merge_event_streams_with_relocation")
    except AttributeError:
        legacy = require_rust_binding("bead_merge_event_streams")
        return {
            "merged": dict(legacy(base, ours, theirs)),
            "relocated": None,
            "relocations": [],
        }
    return dict(binding(base, ours, theirs, relocation_issue_id))


def reduce_event_streams(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    binding = require_rust_binding("bead_reduce_event_streams")
    return list(binding(streams))


def event_store_manifest(streams: list[dict[str, Any]]) -> dict[str, Any]:
    binding = require_rust_binding("bead_event_store_manifest")
    return dict(binding(streams))


def repair_event_store_manifest(beads_dir: str | Path) -> dict[str, Any]:
    # Rewrites ``events/manifest.json`` inside the store, so it is a bead-store
    # write chokepoint alongside the mutation facade and the CLI fast path.
    assert_bead_store_write_sandboxed(
        beads_dir, operation="repair_event_store_manifest"
    )
    binding = require_rust_binding("bead_repair_event_store_manifest")
    return dict(binding(str(Path(beads_dir))))

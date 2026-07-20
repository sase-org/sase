"""Python facade for Rust-backed bead event conflict helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding


def merge_event_streams(
    base: dict[str, Any],
    ours: dict[str, Any],
    theirs: dict[str, Any],
) -> dict[str, Any]:
    binding = require_rust_binding("bead_merge_event_streams")
    return dict(binding(base, ours, theirs))


def reduce_event_streams(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    binding = require_rust_binding("bead_reduce_event_streams")
    return list(binding(streams))


def event_store_manifest(streams: list[dict[str, Any]]) -> dict[str, Any]:
    binding = require_rust_binding("bead_event_store_manifest")
    return dict(binding(streams))


def repair_event_store_manifest(beads_dir: str | Path) -> dict[str, Any]:
    binding = require_rust_binding("bead_repair_event_store_manifest")
    return dict(binding(str(Path(beads_dir))))

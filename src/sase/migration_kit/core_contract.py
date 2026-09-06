"""Rust migration-contract facade used by the temporary host driver.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from sase.core.rust import require_rust_binding


def migration_wire_schema_version() -> int:
    """Return the shared migration wire schema version."""
    return int(require_rust_binding("migration_wire_schema_version")())


def normalize_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Round-trip *manifest* through the Rust ``MigrationManifest`` contract."""
    normalized = require_rust_binding("migration_manifest_normalize")(dict(manifest))
    return dict(normalized)


def normalize_journal_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Round-trip *record* through the Rust ``MigrationJournalRecord`` contract."""
    normalized = require_rust_binding("migration_journal_record_normalize")(
        dict(record)
    )
    return dict(normalized)


def plan_next_step(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    observed_source_digests: Mapping[str, str],
) -> dict[str, Any]:
    """Replay journal records and return the next resumable migration step."""
    normalized = require_rust_binding("migration_plan_next_step")(
        dict(manifest),
        [dict(record) for record in records],
        dict(observed_source_digests),
    )
    return dict(normalized)


def tree_digest(root: Path) -> dict[str, Any]:
    """Return the shared structural tree digest for *root*."""
    digest = require_rust_binding("migration_tree_digest")(str(root))
    return dict(digest)


def fingerprint(value: Any) -> str:
    """Return the shared semantic fingerprint for a JSON-like record stream."""
    return str(require_rust_binding("migration_fingerprint")(value))


def classify_residue(
    entry: Mapping[str, Any], facts: Mapping[str, Any]
) -> dict[str, Any]:
    """Classify one residue entry through the Rust contract."""
    classification = require_rust_binding("migration_residue_classify")(
        dict(entry), dict(facts)
    )
    return dict(classification)


def reconcile_procs(
    legacy_rows: Sequence[Mapping[str, Any]],
    canonical_proc_refs: Sequence[Mapping[str, Any] | str],
) -> dict[str, Any]:
    """Return the shared proc-residue reconciliation plan."""
    plan = require_rust_binding("migration_reconcile_procs")(
        [dict(row) for row in legacy_rows],
        [
            dict(proc_ref) if isinstance(proc_ref, Mapping) else str(proc_ref)
            for proc_ref in canonical_proc_refs
        ],
    )
    return dict(plan)


@contextmanager
def bounded_lock(
    lock_path: Path,
    *,
    timeout_ms: int,
    operation: str,
) -> Iterator[Any]:
    """Acquire and release a bounded migration lock from the Rust core."""
    lock = require_rust_binding("migration_acquire_bounded_lock")(
        str(lock_path), int(timeout_ms), operation
    )
    try:
        yield lock
    finally:
        release = getattr(lock, "release", None)
        if callable(release):
            release()


__all__ = [
    "bounded_lock",
    "classify_residue",
    "fingerprint",
    "migration_wire_schema_version",
    "normalize_journal_record",
    "normalize_manifest",
    "plan_next_step",
    "reconcile_procs",
    "tree_digest",
]

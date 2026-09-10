"""Sidecar index writes for drained artifact-link outbox entries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sase.sdd._artifact_link_outbox_types import (
    ArtifactLinkOutboxEntry as _ArtifactLinkOutboxEntry,
    row_key as _row_key,
    row_uses as _row_uses,
    rows_from_events as _rows_from_events,
)
from sase.sdd._artifact_link_store_support import (
    sidecar_index_path,
    validate_artifact_link_row,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore


def upsert_publishable_entries(
    store: ArtifactLinkStore,
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> list[Path]:
    changed_indexes: list[Path] = []
    for row in _converged_rows(entries):
        existing_uses = _existing_uses(store, row)
        desired_uses = _row_uses(row)
        if str(row.get("origin") or "") == "read":
            # A queued read row only ever knows this batch's own increment
            # (see `_converged_rows`), never the durable total, so the
            # target is what's already on disk plus that increment.
            desired_uses += existing_uses
        if existing_uses >= desired_uses:
            changed_indexes.extend(_existing_index_paths(store, row))
            continue
        delta = dict(row)
        delta["uses"] = desired_uses - existing_uses
        outcome = store.upsert_row(delta)
        changed_indexes.extend(outcome.get("changed_indexes") or ())
    return list(dict.fromkeys(changed_indexes))


def _converged_rows(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[dict[str, Any], ...]:
    """Return legacy rows that preserve queued operation identity.

    Schema-v2 event entries reduce through the Rust event reducer, so distinct
    operation ids remain distinct observations and exact duplicate delivery is
    idempotent. Row-only entries keep the legacy convergence rules for queues
    written before the operation journal.
    """

    event_entries: list[_ArtifactLinkOutboxEntry] = []
    legacy_entries: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if entry.event is not None:
            event_entries.append(entry)
        else:
            legacy_entries.append(entry)

    rows: list[dict[str, Any]] = []
    rows.extend(_rows_from_events(entry.event for entry in event_entries))
    rows.extend(_converged_legacy_rows(legacy_entries))
    return tuple(rows)


def _converged_legacy_rows(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[dict[str, Any], ...]:
    """Combine row-only legacy entries sharing one logical edge."""

    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for entry in entries:
        if entry.row is None:
            continue
        key = entry.logical_key
        if key not in by_key:
            order.append(key)
            by_key[key] = dict(entry.row)
            continue
        current = by_key[key]
        if str(entry.row.get("origin") or "") == "read":
            merged = dict(entry.row)
            merged["uses"] = _row_uses(current) + _row_uses(entry.row)
            by_key[key] = merged
        elif _row_uses(entry.row) >= _row_uses(current):
            by_key[key] = dict(entry.row)
    return tuple(validate_artifact_link_row(by_key[key]) for key in order)


def _existing_uses(store: ArtifactLinkStore, row: Mapping[str, Any]) -> int:
    source, relation, target = _row_key(row)
    candidates = [
        *store.load_artifact_rows(source),
        *store.load_artifact_rows(target),
    ]
    return max(
        (
            _row_uses(candidate)
            for candidate in candidates
            if _row_key(candidate) == (source, relation, target)
        ),
        default=0,
    )


def _existing_index_paths(
    store: ArtifactLinkStore, row: Mapping[str, Any]
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for ref in (str(row.get("source_ref") or ""), str(row.get("target_ref") or "")):
        root = store.sidecar_root_for(ref)
        if root is None:
            continue
        path = sidecar_index_path(root, ref)
        if path.is_file():
            paths.append(path)
    return tuple(dict.fromkeys(paths))


def commit_outbox_indexes(
    store: ArtifactLinkStore,
    changed_indexes: list[Path],
    *,
    push_after_commit: bool | str | None,
) -> bool:
    from sase.sdd._artifact_link_commit import commit_artifact_link_indexes

    result = commit_artifact_link_indexes(
        changed_indexes,
        store=store.sdd_store,
        repo_roots=tuple(store.sidecar_roots.values()),
        push_after_commit=push_after_commit,  # type: ignore[arg-type]
        mutation_origin="machine",
    )
    return bool(result)


__all__ = [
    "commit_outbox_indexes",
    "upsert_publishable_entries",
]

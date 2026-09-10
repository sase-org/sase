"""Local bead and aggregate projections for published artifact-link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import (
    ArtifactLinkEventObject as _ArtifactLinkEventObject,
    edge_from_row as _edge_from_row,
    event_remove_row as _event_remove_row,
    probe_row_from_edge as _probe_row_from_edge,
    reduce_events as _reduce_events,
    row_uses as _row_uses,
    rows_from_events,
)
from sase.sdd._artifact_link_store_support import validate_artifact_link_row
from sase.sdd.artifact_link_store import ArtifactLinkStore


def active_operation_ids_for_row(
    store: ArtifactLinkStore,
    row: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return active event-version operation ids for *row*'s canonical edge."""

    edge = _edge_from_row(validate_artifact_link_row(row))
    return _active_operation_ids_for_edge(store, edge)


def _active_operation_ids_for_edge(
    store: ArtifactLinkStore,
    edge: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return active event-version operation ids for a canonical event edge."""

    events = tuple(event.event for event in _iter_event_objects(store))
    if not events:
        return ()
    reduction = _reduce_events(events)
    reduced_edges = reduction.get("edges")
    if not isinstance(reduced_edges, list):
        return ()
    canonical_edge = _edge_from_row(_probe_row_from_edge(edge))
    for reduced in reduced_edges:
        if not isinstance(reduced, dict):
            continue
        if reduced.get("edge") != canonical_edge:
            continue
        versions = reduced.get("versions")
        if not isinstance(versions, list):
            return ()
        return tuple(
            str(version.get("operation_id") or "")
            for version in versions
            if isinstance(version, dict) and bool(version.get("active"))
        )
    return ()


def apply_events_to_beads(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
) -> bool:
    if store.beads_dir is None or not objects:
        return False
    from sase.sdd.artifact_link_beads import (
        add_bead_endpoint_link,
        remove_bead_endpoint_link,
    )

    changed = False
    for item in objects:
        event = item.event
        operation_id = str(event["operation_id"])
        event_kind = event.get("kind")
        if not isinstance(event_kind, dict):
            continue
        event_type = str(event_kind.get("type") or "")
        if event_type == "edge-remove":
            row = _event_remove_row(event)
            if row is None:
                continue
            for issue_id, target_ref, direction in _bead_endpoint_writes(row):
                outcome = remove_bead_endpoint_link(
                    store.beads_dir,
                    issue_id=issue_id,
                    target_ref=target_ref,
                    relation=str(row.get("relation") or ""),
                    direction=direction,
                    now=str(event.get("created_at") or "") or None,
                    operation_id=operation_id,
                )
                changed = changed or bool(outcome.get("changed"))
            continue
        for row in _event_rows_for_beads(event):
            for issue_id, target_ref, direction in _bead_endpoint_writes(row):
                outcome = add_bead_endpoint_link(
                    store.beads_dir,
                    issue_id=issue_id,
                    target_ref=target_ref,
                    relation=str(row.get("relation") or ""),
                    description=str(row.get("description") or ""),
                    origin=str(row.get("origin") or ""),
                    direction=direction,
                    uses=_row_uses(row),
                    now=str(row.get("created_at") or "") or None,
                    operation_id=operation_id,
                )
                changed = changed or bool(outcome.get("changed"))

    if not changed:
        return False
    from sase.sdd._artifact_link_commit import (
        ArtifactLinkPersistError,
        commit_bead_link_events,
    )

    try:
        commit_bead_link_events(
            store,
            artifacts_dir=artifacts_dir,
            mutation_origin=mutation_origin,
        )
    except ArtifactLinkPersistError:
        raise
    return True


def _event_rows_for_beads(event: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    kind = event.get("kind")
    if isinstance(kind, dict) and str(kind.get("type") or "") == "baseline-import":
        rows = kind.get("rows")
        if isinstance(rows, list):
            return tuple(
                validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
            )
    return rows_from_events((event,))


def _bead_endpoint_writes(
    row: Mapping[str, Any],
) -> tuple[tuple[str, str, str], ...]:
    from sase.sdd.artifact_link_beads import bead_id_from_ref

    source_ref = str(row.get("source_ref") or "")
    target_ref = str(row.get("target_ref") or "")
    writes: list[tuple[str, str, str]] = []
    source_issue_id = bead_id_from_ref(source_ref)
    if source_issue_id is not None:
        writes.append((source_issue_id, target_ref, "out"))
    target_issue_id = bead_id_from_ref(target_ref)
    if target_issue_id is not None and target_issue_id != source_issue_id:
        writes.append((target_issue_id, source_ref, "in"))
    return tuple(writes)


def apply_events_to_aggregate(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
) -> tuple[dict[str, Any], ...]:
    for item in objects:
        row = _event_remove_row(item.event)
        if row is None:
            continue
        store._remove_aggregate_rows(
            source=str(row.get("source_ref") or ""),
            target=str(row.get("target_ref") or ""),
            relation=str(row.get("relation") or "") or None,
        )
    rows = rows_from_events(item.event for item in objects)
    written: list[dict[str, Any]] = []
    for row in rows:
        outcome = store._upsert_aggregate_row(row)
        stored = outcome.get("row")
        if isinstance(stored, dict):
            written.append(dict(stored))
    return tuple(written)


def _iter_event_objects(store: ArtifactLinkStore) -> Iterable[_ArtifactLinkEventObject]:
    seen_roots: set[Path] = set()
    for root in store.sidecar_roots.values():
        resolved = root.expanduser().resolve(strict=False)
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        events_root = resolved / "link-events" / "v1"
        if not events_root.is_dir():
            continue
        for path in sorted(events_root.rglob("*.json")):
            try:
                payload = path.read_bytes()
                relative = path.relative_to(resolved).as_posix()
                validated = dict(
                    require_rust_binding("artifact_link_event_validate_bytes")(
                        payload,
                        relative,
                    )
                )
            except Exception:
                continue
            yield _ArtifactLinkEventObject(
                event=dict(validated["event"]),
                canonical_json=str(validated["canonical_json"]),
                payload=payload,
                digest=str(validated["digest"]),
                relative_path=Path(str(validated["path"])),
            )

"""Local bead and aggregate projections for published artifact-link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import (
    ArtifactLinkEventObject as _ArtifactLinkEventObject,
    edge_from_row as _edge_from_row,
    event_remove_row as _event_remove_row,
    probe_row_from_edge as _probe_row_from_edge,
    reduce_events as _reduce_events,
    rows_from_events,
)
from sase.sdd._artifact_link_event_local_store import artifact_link_local_event_root
from sase.sdd._artifact_link_event_store import reduce_artifact_link_event_inputs
from sase.sdd._artifact_link_store_support import validate_artifact_link_row
from sase.sdd.artifact_link_store import ArtifactLinkStore

BEAD_PROJECTION_BATCH_SIZE = 64
BEAD_PROJECTION_DEFERRED_DIAGNOSTIC = "deferred past job budget"


@dataclass(frozen=True, slots=True)
class _ArtifactLinkBeadProjectionResult:
    """Durability receipt for bead endpoint projection."""

    changed: bool
    receipt: bool
    diagnostic: str | None = None
    deferred: bool = False


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
    force: bool = False,
    deadline: float | None = None,
) -> _ArtifactLinkBeadProjectionResult:
    if not objects and not force:
        return _ArtifactLinkBeadProjectionResult(changed=False, receipt=True)
    if store.beads_dir is None:
        return _ArtifactLinkBeadProjectionResult(
            changed=False,
            receipt=False,
            diagnostic="artifact-link bead store is unavailable",
        )
    authorization_error = _bead_projection_authorization_error(
        store.beads_dir,
        mutation_origin=mutation_origin,
    )
    if authorization_error is not None:
        return _ArtifactLinkBeadProjectionResult(
            changed=False,
            receipt=False,
            diagnostic=authorization_error,
        )
    from sase.sdd.artifact_link_beads import set_bead_endpoint_projections
    from sase.sdd._artifact_link_commit import ArtifactLinkPersistError

    changed = False
    try:
        if _deadline_expired(deadline):
            return _finalize_bead_projection(
                store,
                artifacts_dir=artifacts_dir,
                mutation_origin=mutation_origin,
                changed=False,
                deferred=True,
            )
        store_events = tuple(event.event for event in _iter_event_objects(store))
        incoming_events = tuple(item.event for item in objects)
        union_events = (*store_events, *incoming_events)
        snapshot = reduce_artifact_link_event_inputs(
            durable_events=union_events,
            strict=True,
        )
        desired, active_operations, affected = _desired_endpoint_projections(
            snapshot.edges
        )
        raw_operations = _raw_endpoint_operations(union_events)
        affected.update(raw_operations)
        scoped = (
            affected
            if force
            else _scope_endpoint_keys(
                incoming_events,
                snapshot=snapshot,
                active_operations=active_operations,
                raw_operations=raw_operations,
                all_keys=affected,
            )
        )
        requests: list[dict[str, Any]] = []
        for key in sorted(scoped):
            requests.extend(
                _projection_requests_for_key(
                    key,
                    desired=desired,
                    active_operations=active_operations,
                    raw_operations=raw_operations,
                )
            )
        batch_size = max(1, BEAD_PROJECTION_BATCH_SIZE)
        for offset in range(0, len(requests), batch_size):
            if _deadline_expired(deadline):
                return _finalize_bead_projection(
                    store,
                    artifacts_dir=artifacts_dir,
                    mutation_origin=mutation_origin,
                    changed=changed,
                    deferred=True,
                )
            chunk = requests[offset : offset + batch_size]
            outcome = set_bead_endpoint_projections(store.beads_dir, chunk)
            changed = changed or bool(outcome.get("changed"))

        return _finalize_bead_projection(
            store,
            artifacts_dir=artifacts_dir,
            mutation_origin=mutation_origin,
            changed=changed,
            deferred=False,
        )
    except ArtifactLinkPersistError as exc:
        return _ArtifactLinkBeadProjectionResult(
            changed=changed,
            receipt=False,
            diagnostic=exc.diagnostic,
        )
    except Exception as exc:  # noqa: BLE001 - outbox replay must retry cleanly.
        return _ArtifactLinkBeadProjectionResult(
            changed=changed,
            receipt=False,
            diagnostic=str(exc),
        )


def _finalize_bead_projection(
    store: ArtifactLinkStore,
    *,
    artifacts_dir: str | Path | None,
    mutation_origin: str,
    changed: bool,
    deferred: bool,
) -> _ArtifactLinkBeadProjectionResult:
    from sase.sdd._artifact_link_commit import commit_bead_link_events

    assert store.beads_dir is not None
    if changed or _bead_store_has_uncommitted_changes(store.beads_dir):
        commit_bead_link_events(
            store,
            artifacts_dir=artifacts_dir,
            mutation_origin=mutation_origin,
        )
    if _bead_store_has_uncommitted_changes(store.beads_dir):
        return _ArtifactLinkBeadProjectionResult(
            changed=changed,
            receipt=False,
            diagnostic="artifact-link bead projection has uncommitted changes",
            deferred=deferred,
        )
    if deferred:
        return _ArtifactLinkBeadProjectionResult(
            changed=changed,
            receipt=False,
            diagnostic=BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
            deferred=True,
        )
    return _ArtifactLinkBeadProjectionResult(changed=changed, receipt=True)


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _projection_requests_for_key(
    key: _EndpointKey,
    *,
    desired: Mapping[_EndpointKey, Mapping[str, Any]],
    active_operations: Mapping[_EndpointKey, tuple[str, ...]],
    raw_operations: Mapping[_EndpointKey, tuple[str, ...]],
) -> tuple[dict[str, Any], ...]:
    issue_id, target_ref, relation, direction = key
    row = desired.get(key)
    operation_ids = (
        active_operations.get(key) or raw_operations.get(key, ())
        if row is not None
        else raw_operations.get(key, ())
    )
    if not operation_ids:
        return ()
    now = str(row.get("created_at") or "") or None if row is not None else None
    return tuple(
        {
            "issue_id": issue_id,
            "target_ref": target_ref,
            "relation": relation,
            "direction": direction,
            "operation_id": operation_id,
            "row": row,
            "now": now,
        }
        for operation_id in operation_ids
    )


def _scope_endpoint_keys(
    incoming_events: Sequence[Mapping[str, Any]],
    *,
    snapshot: object,
    active_operations: Mapping[_EndpointKey, tuple[str, ...]],
    raw_operations: Mapping[_EndpointKey, tuple[str, ...]],
    all_keys: set[_EndpointKey],
) -> set[_EndpointKey]:
    incoming_raw = _raw_endpoint_operations(incoming_events)
    scope = set(incoming_raw)
    incoming_operation_ids = {
        str(event.get("operation_id") or "")
        for event in incoming_events
        if str(event.get("operation_id") or "")
    }
    for key, operation_ids in (*active_operations.items(), *raw_operations.items()):
        if incoming_operation_ids.intersection(operation_ids):
            scope.add(key)
    aliases = tuple(getattr(snapshot, "aliases", ()) or ())
    alias_refs: set[str] = set()
    for event in incoming_events:
        alias = _event_alias_refs(event)
        if alias is not None:
            alias_refs.update(alias)
        for row in _event_rows_for_beads(event):
            scope.update(_endpoint_keys_for_row(row))
            resolved = _row_with_aliases(row, aliases)
            if resolved is not None:
                scope.update(_endpoint_keys_for_row(resolved))
    if alias_refs:
        for key in all_keys:
            if _endpoint_touches_refs(key, alias_refs):
                scope.add(key)
        for key in incoming_raw:
            if _endpoint_touches_refs(key, alias_refs):
                scope.add(key)
    return scope


def _event_alias_refs(event: Mapping[str, Any]) -> tuple[str, str] | None:
    kind = event.get("kind")
    if not isinstance(kind, dict) or str(kind.get("type") or "") != "alias":
        return None
    old_ref = str(kind.get("old_ref") or "")
    new_ref = str(kind.get("new_ref") or "")
    if not old_ref or not new_ref:
        return None
    return old_ref, new_ref


def _row_with_aliases(
    row: Mapping[str, Any],
    aliases: Sequence[Mapping[str, str]],
) -> dict[str, Any] | None:
    if not aliases:
        return None
    mapping = {
        str(alias.get("old_ref") or ""): str(alias.get("new_ref") or "")
        for alias in aliases
        if str(alias.get("old_ref") or "") and str(alias.get("new_ref") or "")
    }
    if not mapping:
        return None
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    resolved_source = mapping.get(source, source)
    resolved_target = mapping.get(target, target)
    if resolved_source == source and resolved_target == target:
        return None
    resolved = dict(row)
    resolved["source_ref"] = resolved_source
    resolved["target_ref"] = resolved_target
    return resolved


def _endpoint_touches_refs(key: _EndpointKey, refs: set[str]) -> bool:
    from sase.sdd.artifact_link_beads import bead_source_ref

    issue_id, target_ref, _relation, _direction = key
    return target_ref in refs or bead_source_ref(issue_id) in refs


def _event_rows_for_beads(event: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    kind = event.get("kind")
    if isinstance(kind, dict) and str(kind.get("type") or "") == "baseline-import":
        rows = kind.get("rows")
        if isinstance(rows, list):
            return tuple(
                validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
            )
    if isinstance(kind, dict) and str(kind.get("type") or "") == "edge-remove":
        row = _event_remove_row(event)
        return () if row is None else (row,)
    return rows_from_events((event,))


_EndpointKey = tuple[str, str, str, str]


def _desired_endpoint_projections(
    reduced_edges: Iterable[Mapping[str, Any]],
) -> tuple[
    dict[_EndpointKey, dict[str, Any]],
    dict[_EndpointKey, tuple[str, ...]],
    set[_EndpointKey],
]:
    desired: dict[_EndpointKey, dict[str, Any]] = {}
    active_operations: dict[_EndpointKey, tuple[str, ...]] = {}
    affected: set[_EndpointKey] = set()
    for edge_record in reduced_edges:
        if not isinstance(edge_record, Mapping):
            continue
        row = edge_record.get("row")
        active_row = (
            validate_artifact_link_row(row) if isinstance(row, Mapping) else None
        )
        probe = active_row
        if probe is None:
            edge = edge_record.get("edge")
            if not isinstance(edge, Mapping):
                continue
            try:
                probe = validate_artifact_link_row(_probe_row_from_edge(edge))
            except (TypeError, ValueError, RuntimeError):
                continue
        keys = tuple(_endpoint_keys_for_row(probe))
        affected.update(keys)
        if active_row is None:
            continue
        operation_ids = _active_version_operation_ids(edge_record)
        for key in keys:
            desired[key] = active_row
            active_operations[key] = operation_ids
    return desired, active_operations, affected


def _raw_endpoint_operations(
    events: Iterable[Mapping[str, Any]],
) -> dict[_EndpointKey, tuple[str, ...]]:
    operations: dict[_EndpointKey, list[str]] = {}
    for event in events:
        operation_id = str(event.get("operation_id") or "")
        if not operation_id:
            continue
        for row in _event_rows_for_beads(event):
            for key in _endpoint_keys_for_row(row):
                operations.setdefault(key, []).append(operation_id)
    return {
        key: tuple(dict.fromkeys(operation_ids))
        for key, operation_ids in operations.items()
    }


def _active_version_operation_ids(edge_record: Mapping[str, Any]) -> tuple[str, ...]:
    versions = edge_record.get("versions")
    if not isinstance(versions, list):
        return ()
    return tuple(
        dict.fromkeys(
            str(version.get("operation_id") or "")
            for version in versions
            if isinstance(version, Mapping) and bool(version.get("active"))
        )
    )


def _endpoint_keys_for_row(row: Mapping[str, Any]) -> Iterable[_EndpointKey]:
    relation = str(row.get("relation") or "")
    for issue_id, target_ref, direction in _bead_endpoint_writes(row):
        yield (issue_id, target_ref, relation, direction)


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


def _bead_store_has_uncommitted_changes(beads_dir: Path) -> bool:
    git_root = _git_root_for(beads_dir)
    if git_root is None:
        return False
    try:
        scope = os.path.relpath(beads_dir, git_root)
    except ValueError:
        scope = "."
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            scope,
        ],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def _bead_projection_authorization_error(
    beads_dir: Path, *, mutation_origin: str
) -> str | None:
    from sase.workspace_provider.ownership import (
        WorkspaceOwnershipError,
        authorize_store_mutation,
    )

    repo = beads_dir if (beads_dir / ".git").is_dir() else beads_dir.parent
    try:
        authorize_store_mutation(repo, mutation_origin=mutation_origin)
    except WorkspaceOwnershipError as exc:
        return str(exc)
    return None


def _git_root_for(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def apply_events_to_aggregate(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
) -> tuple[dict[str, Any], ...]:
    if not objects:
        return ()
    if all(_event_type(item.event) == "baseline-import" for item in objects):
        return ()
    aggregate = store.rebuild_aggregate(
        exclude_pending_event_ids=(str(item.event["operation_id"]) for item in objects),
    )
    return tuple(
        dict(row) for row in aggregate.get("rows", ()) if isinstance(row, dict)
    )


def _event_type(event: Mapping[str, Any]) -> str:
    kind = event.get("kind")
    if not isinstance(kind, dict):
        return ""
    return str(kind.get("type") or "")


def _iter_event_objects(store: ArtifactLinkStore) -> Iterable[_ArtifactLinkEventObject]:
    seen_roots: set[Path] = set()
    roots = (
        *store.sidecar_roots.values(),
        artifact_link_local_event_root(store.project_key),
    )
    for root in roots:
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


__all__ = [
    "BEAD_PROJECTION_BATCH_SIZE",
    "BEAD_PROJECTION_DEFERRED_DIAGNOSTIC",
    "active_operation_ids_for_row",
    "apply_events_to_aggregate",
    "apply_events_to_beads",
]

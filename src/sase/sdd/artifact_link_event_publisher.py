"""Immutable artifact-link event publication through document sidecars."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Literal

from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_commit import (
    ArtifactLinkPersistError,
    commit_artifact_link_indexes,
)
from sase.sdd._artifact_link_store_support import (
    kind_of_ref,
    validate_artifact_link_row,
)
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)

ARTIFACT_LINK_EVENT_COMMIT_MESSAGE = "chore(artifact-links): persist link events"
ARTIFACT_LINK_EVENT_LOCK_FILENAME = "artifact-link-events.lock"
EVENT_SCHEMA_VERSION = 1


class _ArtifactLinkEventPublishError(RuntimeError):
    """Raised when an immutable event cannot be made locally durable."""


class _ArtifactLinkEventCorruptionError(_ArtifactLinkEventPublishError):
    """Raised when a content-addressed event path already has different bytes."""


@dataclass(frozen=True, slots=True)
class _ArtifactLinkEventObject:
    """Canonical immutable event payload plus its content-addressed location."""

    event: dict[str, Any]
    canonical_json: str
    payload: bytes
    digest: str
    relative_path: Path


@dataclass(frozen=True, slots=True)
class _ArtifactLinkEventRootOutcome:
    """Per-root result for one event object."""

    root: Path
    relative_path: Path
    created: bool
    committed: bool
    durable: bool

    @property
    def path(self) -> Path:
        return self.root / self.relative_path


@dataclass(frozen=True, slots=True)
class _ArtifactLinkEventPublishReport:
    """Result of one immutable event publication batch."""

    attempted: int
    published: int = 0
    committed: bool = False
    event_paths: tuple[Path, ...] = ()
    durable_event_paths: tuple[Path, ...] = ()
    published_operation_ids: tuple[str, ...] = ()
    beads_changed: bool = False
    aggregate_rows: tuple[dict[str, Any], ...] = ()
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()


def _canonical_artifact_link_event_object(
    event: Mapping[str, Any],
) -> _ArtifactLinkEventObject:
    """Return canonical bytes, digest, and path for one event via Rust."""

    canonical = dict(
        require_rust_binding("artifact_link_event_canonicalize")(dict(event))
    )
    canonical_json = str(
        require_rust_binding("artifact_link_event_canonical_json")(canonical)
    )
    payload = canonical_json.encode("utf-8")
    digest = str(require_rust_binding("artifact_link_event_digest")(canonical))
    relative = Path(
        str(require_rust_binding("artifact_link_event_path_for_digest")(digest))
    )
    validated = dict(
        require_rust_binding("artifact_link_event_validate_bytes")(
            payload,
            relative.as_posix(),
        )
    )
    return _ArtifactLinkEventObject(
        event=dict(validated["event"]),
        canonical_json=str(validated["canonical_json"]),
        payload=payload,
        digest=str(validated["digest"]),
        relative_path=Path(str(validated["path"])),
    )


def stable_artifact_link_operation_id(*parts: object) -> str:
    """Return a deterministic 128-bit operation id for replayable writers."""

    payload = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def observation_or_put_event_from_row(
    row: Mapping[str, Any],
    *,
    project_key: str,
    operation_id: str,
) -> dict[str, Any]:
    """Build a canonical observation or edge-put event from one legacy row."""

    canonical_row = validate_artifact_link_row(row)
    origin = str(canonical_row.get("origin") or "")
    edge = _edge_from_row(canonical_row)
    if origin in {"read", "prompt_ref"}:
        kind = {
            "type": "observation",
            "edge": edge,
            "description": str(canonical_row.get("description") or ""),
            "occurrences": _row_uses(canonical_row),
        }
    else:
        kind = {
            "type": "edge-put",
            "edge": edge,
            "description": str(canonical_row.get("description") or ""),
            "observed_operation_ids": [],
        }
    return canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": project_key,
            "operation_id": operation_id,
            "created_by": str(canonical_row.get("created_by") or ""),
            "origin": origin,
            "created_at": str(canonical_row.get("created_at") or ""),
            "kind": kind,
        }
    )


def edge_put_event_from_row(
    row: Mapping[str, Any],
    *,
    project_key: str,
    operation_id: str,
    observed_operation_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a canonical explicit edge-put event from one row."""

    canonical_row = validate_artifact_link_row(row)
    return canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": project_key,
            "operation_id": operation_id,
            "created_by": str(canonical_row.get("created_by") or ""),
            "origin": str(canonical_row.get("origin") or ""),
            "created_at": str(canonical_row.get("created_at") or ""),
            "kind": {
                "type": "edge-put",
                "edge": _edge_from_row(canonical_row),
                "description": str(canonical_row.get("description") or ""),
                "observed_operation_ids": list(observed_operation_ids),
            },
        }
    )


def edge_remove_event(
    *,
    project_key: str,
    operation_id: str,
    source_ref: str,
    relation: str,
    target_ref: str,
    created_by: str,
    origin: str,
    created_at: str,
    observed_operation_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a canonical explicit edge-remove event."""

    return canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": project_key,
            "operation_id": operation_id,
            "created_by": created_by,
            "origin": origin,
            "created_at": created_at,
            "kind": {
                "type": "edge-remove",
                "edge": {
                    "kind": "directed",
                    "source_ref": source_ref,
                    "relation": relation,
                    "target_ref": target_ref,
                },
                "observed_operation_ids": list(observed_operation_ids),
            },
        }
    )


def canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize one event through the Rust event contract."""

    return dict(require_rust_binding("artifact_link_event_canonicalize")(dict(event)))


def _artifact_link_event_schema_version() -> int:
    """Return the Rust event schema version."""

    return int(require_rust_binding("artifact_link_event_schema_version")())


def _edge_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical event edge for one validated row."""

    event = canonical_event(
        {
            "schema_version": _artifact_link_event_schema_version(),
            "project_key": "edge_probe",
            "operation_id": "00000000000000000000000000000000",
            "created_by": "sase",
            "origin": "manual",
            "created_at": "1970-01-01T00:00:00Z",
            "kind": {
                "type": "edge-put",
                "edge": {
                    "kind": "directed",
                    "source_ref": str(row.get("source_ref") or ""),
                    "relation": str(row.get("relation") or ""),
                    "target_ref": str(row.get("target_ref") or ""),
                },
                "description": str(row.get("description") or "edge probe"),
                "observed_operation_ids": [],
            },
        }
    )
    kind = event.get("kind")
    if not isinstance(kind, dict):
        raise RuntimeError("sase_core_rs returned malformed artifact-link event kind")
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        raise RuntimeError("sase_core_rs returned malformed artifact-link event edge")
    return dict(edge)


def rows_from_events(
    events: Iterable[Mapping[str, Any] | None],
) -> tuple[dict[str, Any], ...]:
    """Reduce canonical events into legacy row projections via Rust."""

    reduction = _reduce_events(events)
    rows = reduction.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("sase_core_rs returned malformed link-event rows")
    return tuple(
        validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
    )


def _reduce_events(events: Iterable[Mapping[str, Any] | None]) -> dict[str, Any]:
    """Reduce canonical events and return Rust reduction metadata."""

    canonical_events = [canonical_event(event) for event in events if event is not None]
    if not canonical_events:
        return {"schema_version": EVENT_SCHEMA_VERSION, "rows": [], "edges": []}
    reduction = require_rust_binding("artifact_link_events_reduce")(
        canonical_events,
        [],
    )
    if not isinstance(reduction, Mapping):
        raise RuntimeError("sase_core_rs returned malformed link-event reduction")
    return dict(reduction)


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


def publish_artifact_link_events(
    store: ArtifactLinkStore,
    events: Iterable[Mapping[str, Any]],
    *,
    push_after_commit: bool | Literal["async"] | None = "async",
    mutation_origin: str = "machine",
    artifacts_dir: str | Path | None = None,
) -> _ArtifactLinkEventPublishReport:
    """Publish immutable link events and update local non-durable projections."""

    objects = _dedupe_event_objects(
        _canonical_artifact_link_event_object(event) for event in events
    )
    if not objects:
        return _ArtifactLinkEventPublishReport(attempted=0)

    lock_path = (
        sase_projects_dir() / store.project_key / ARTIFACT_LINK_EVENT_LOCK_FILENAME
    )
    with locked_file(lock_path, fcntl.LOCK_EX):
        return _publish_event_objects_locked(
            store,
            objects,
            push_after_commit=push_after_commit,
            mutation_origin=mutation_origin,
            artifacts_dir=artifacts_dir,
        )


def _publish_event_objects_locked(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    push_after_commit: bool | Literal["async"] | None,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
) -> _ArtifactLinkEventPublishReport:
    roots_by_operation = _roots_by_operation(store, objects)
    grouped = _objects_by_root_for(objects, roots_by_operation)
    durable: dict[str, set[Path]] = {
        str(item.event["operation_id"]): set() for item in objects
    }
    event_paths: list[Path] = []
    durable_paths: list[Path] = []
    diagnostics: list[str] = []
    publication_errors: list[str] = []
    committed = False

    for root, root_objects in grouped.items():
        outcome = _publish_root_events(
            store,
            root,
            root_objects,
            push_after_commit=push_after_commit,
            mutation_origin=mutation_origin,
            artifacts_dir=artifacts_dir,
        )
        committed = committed or any(item.committed for item in outcome.root_outcomes)
        if outcome.publication_error:
            publication_errors.append(outcome.publication_error)
        diagnostics.extend(outcome.skip_diagnostics)
        for root_outcome in outcome.root_outcomes:
            event_paths.append(root_outcome.path)
            if root_outcome.durable:
                durable_paths.append(root_outcome.path)
                operation_id = str(
                    next(
                        event.event["operation_id"]
                        for event in root_objects
                        if event.relative_path == root_outcome.relative_path
                    )
                )
                durable[operation_id].add(root)

    doc_ready = {
        operation_id
        for operation_id, roots in roots_by_operation.items()
        if set(roots) == durable.get(operation_id, set())
    }
    ready_objects = [
        item for item in objects if str(item.event["operation_id"]) in doc_ready
    ]

    bead_ready = True
    beads_changed = False
    try:
        beads_changed = _apply_events_to_beads(
            store,
            ready_objects,
            mutation_origin=mutation_origin,
            artifacts_dir=artifacts_dir,
        )
    except Exception as exc:  # noqa: BLE001 - outbox replay must retry cleanly.
        bead_ready = False
        diagnostics.append(f"artifact-link bead event publication failed: {exc}")

    aggregate_rows: tuple[dict[str, Any], ...] = ()
    aggregate_ready = bead_ready
    if bead_ready:
        try:
            aggregate_rows = _apply_events_to_aggregate(store, ready_objects)
        except Exception as exc:  # noqa: BLE001 - durable events replay idempotently.
            aggregate_ready = False
            diagnostics.append(f"artifact-link aggregate projection failed: {exc}")

    published_ids = (
        tuple(str(item.event["operation_id"]) for item in ready_objects)
        if aggregate_ready
        else ()
    )
    return _ArtifactLinkEventPublishReport(
        attempted=len(objects),
        published=len(published_ids),
        committed=committed or beads_changed,
        event_paths=tuple(dict.fromkeys(event_paths)),
        durable_event_paths=tuple(dict.fromkeys(durable_paths)),
        published_operation_ids=published_ids,
        beads_changed=beads_changed,
        aggregate_rows=aggregate_rows,
        publication_error="\n".join(publication_errors) or None,
        skip_diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


@dataclass(frozen=True, slots=True)
class _RootPublishReport:
    root_outcomes: tuple[_ArtifactLinkEventRootOutcome, ...]
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()


def _publish_root_events(
    store: ArtifactLinkStore,
    root: Path,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    push_after_commit: bool | Literal["async"] | None,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
) -> _RootPublishReport:
    from sase.sdd._git_contention import store_git_write_lock

    root = root.expanduser().resolve(strict=False)
    with store_git_write_lock(
        root,
        op="artifact_link.event_publisher",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            return _RootPublishReport(
                root_outcomes=tuple(
                    _ArtifactLinkEventRootOutcome(
                        root=root,
                        relative_path=item.relative_path,
                        created=False,
                        committed=False,
                        durable=False,
                    )
                    for item in objects
                ),
                skip_diagnostics=(
                    f"artifact-link event publisher could not acquire store lock for {root}",
                ),
            )
        paths: list[Path] = []
        created_paths: set[Path] = set()
        for item in objects:
            path = root / item.relative_path
            if _create_event_file(path, item.payload):
                created_paths.add(path)
            paths.append(path)
        result = commit_artifact_link_indexes(
            paths,
            store=store.sdd_store,
            project_key=store.project_key,
            repo_roots=(root,),
            artifacts_dir=artifacts_dir,
            already_locked=True,
            mutation_origin=mutation_origin,
            push_after_commit=push_after_commit,
            verify_publication=True,
            message=ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
        )
        outcomes = tuple(
            _ArtifactLinkEventRootOutcome(
                root=root,
                relative_path=item.relative_path,
                created=(root / item.relative_path) in created_paths,
                committed=result.committed,
                durable=_head_contains_event(root, item),
            )
            for item in objects
        )
        diagnostics = tuple(
            f"artifact-link event {item.relative_path.as_posix()} is not durable in {root}"
            for item, root_outcome in zip(objects, outcomes, strict=True)
            if not root_outcome.durable
        )
        return _RootPublishReport(
            root_outcomes=outcomes,
            publication_error=result.publication_error,
            skip_diagnostics=diagnostics,
        )


def _create_event_file(path: Path, payload: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as file_exists_exc:
        if path.is_symlink():
            raise _ArtifactLinkEventCorruptionError(
                f"artifact-link event path is a symlink: {path}"
            ) from file_exists_exc
        try:
            existing = path.read_bytes()
        except OSError as read_exc:
            raise _ArtifactLinkEventPublishError(
                f"could not read existing artifact-link event {path}: {read_exc}"
            ) from read_exc
        if existing == payload:
            return False
        raise _ArtifactLinkEventCorruptionError(
            f"artifact-link event path already exists with different bytes: {path}"
        ) from file_exists_exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return True


def _head_contains_event(root: Path, event: _ArtifactLinkEventObject) -> bool:
    if not (root / ".git").is_dir():
        try:
            return (root / event.relative_path).read_bytes() == event.payload
        except OSError:
            return False
    result = subprocess.run(
        ["git", "show", f"HEAD:{event.relative_path.as_posix()}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout == event.payload


def _roots_by_operation(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
) -> dict[str, tuple[Path, ...]]:
    roots: dict[str, tuple[Path, ...]] = {}
    for item in objects:
        operation_id = str(item.event["operation_id"])
        roots[operation_id] = _document_roots_for_event(store, item.event)
    return roots


def _objects_by_root_for(
    objects: Sequence[_ArtifactLinkEventObject],
    roots_by_operation: Mapping[str, Sequence[Path]],
) -> dict[Path, list[_ArtifactLinkEventObject]]:
    grouped: dict[Path, list[_ArtifactLinkEventObject]] = {}
    for item in objects:
        operation_id = str(item.event["operation_id"])
        for root in roots_by_operation.get(operation_id, ()):
            resolved = root.expanduser().resolve(strict=False)
            grouped.setdefault(resolved, []).append(item)
    return grouped


def _document_roots_for_event(
    store: ArtifactLinkStore,
    event: Mapping[str, Any],
) -> tuple[Path, ...]:
    roots: list[Path] = []
    for ref in _document_refs_for_event(event):
        root = store.sidecar_root_for(ref)
        if root is None:
            continue
        resolved = root.expanduser().resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _document_refs_for_event(event: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    kind = event.get("kind")
    if not isinstance(kind, dict):
        return ()
    event_type = str(kind.get("type") or "")
    if event_type in {"observation", "edge-put", "edge-remove"}:
        edge = kind.get("edge")
        if isinstance(edge, dict):
            refs.extend(_edge_refs(edge))
    elif event_type == "alias":
        refs.extend([str(kind.get("old_ref") or ""), str(kind.get("new_ref") or "")])
    elif event_type == "baseline-import":
        rows = kind.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                refs.extend(
                    [
                        str(row.get("source_ref") or ""),
                        str(row.get("target_ref") or ""),
                    ]
                )
    return tuple(
        ref
        for ref in dict.fromkeys(refs)
        if ref and kind_of_ref(ref) not in {"agent", "bead", "stitch"}
    )


def _edge_refs(edge: Mapping[str, Any]) -> tuple[str, str]:
    edge_kind = str(edge.get("kind") or "")
    if edge_kind == "directed":
        return str(edge.get("source_ref") or ""), str(edge.get("target_ref") or "")
    if edge_kind == "undirected":
        return str(edge.get("left_ref") or ""), str(edge.get("right_ref") or "")
    return "", ""


def _dedupe_event_objects(
    objects: Iterable[_ArtifactLinkEventObject],
) -> tuple[_ArtifactLinkEventObject, ...]:
    by_operation: dict[str, _ArtifactLinkEventObject] = {}
    order: list[str] = []
    for item in objects:
        operation_id = str(item.event.get("operation_id") or "")
        existing = by_operation.get(operation_id)
        if existing is not None:
            if existing.canonical_json != item.canonical_json:
                raise _ArtifactLinkEventPublishError(
                    f"operation_id `{operation_id}` was reused for different events"
                )
            continue
        by_operation[operation_id] = item
        order.append(operation_id)
    return tuple(by_operation[operation_id] for operation_id in order)


def _apply_events_to_beads(
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
    from sase.sdd._artifact_link_commit import commit_bead_link_events

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


def _apply_events_to_aggregate(
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


def _event_remove_row(event: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = event.get("kind")
    if not isinstance(kind, dict) or str(kind.get("type") or "") != "edge-remove":
        return None
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        return None
    source, relation, target = _edge_row_parts(edge)
    if not source or not relation or not target:
        return None
    return validate_artifact_link_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": source,
            "relation": relation,
            "target_ref": target,
            "description": "removed artifact link",
            "origin": str(event.get("origin") or "manual"),
            "created_by": str(event.get("created_by") or "sase"),
            "created_at": str(event.get("created_at") or "1970-01-01T00:00:00Z"),
            "uses": 1,
        }
    )


def _edge_row_parts(edge: Mapping[str, Any]) -> tuple[str, str, str]:
    edge_kind = str(edge.get("kind") or "")
    if edge_kind == "directed":
        return (
            str(edge.get("source_ref") or ""),
            str(edge.get("relation") or ""),
            str(edge.get("target_ref") or ""),
        )
    if edge_kind == "undirected":
        return (
            str(edge.get("left_ref") or ""),
            str(edge.get("relation") or ""),
            str(edge.get("right_ref") or ""),
        )
    return "", "", ""


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


def _probe_row_from_edge(edge: Mapping[str, Any]) -> dict[str, Any]:
    source, relation, target = _edge_row_parts(edge)
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": "edge probe",
        "origin": "manual",
        "created_by": "sase",
        "created_at": "1970-01-01T00:00:00Z",
        "uses": 1,
    }


def _row_uses(row: Mapping[str, Any]) -> int:
    try:
        uses = int(row.get("uses") or 0)
    except (TypeError, ValueError):
        return 0
    return max(1, uses)


__all__ = [
    "ARTIFACT_LINK_EVENT_COMMIT_MESSAGE",
    "active_operation_ids_for_row",
    "canonical_event",
    "edge_put_event_from_row",
    "edge_remove_event",
    "observation_or_put_event_from_row",
    "publish_artifact_link_events",
    "rows_from_events",
    "stable_artifact_link_operation_id",
]

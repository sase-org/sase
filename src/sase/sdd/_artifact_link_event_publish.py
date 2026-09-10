"""Durable sidecar writes for immutable artifact-link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import subprocess
from typing import Any, Literal

from sase.core.paths import sase_projects_dir
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_commit import (
    artifact_link_publication_error_for_roots,
    commit_artifact_link_indexes,
)
from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
    ARTIFACT_LINK_EVENT_LOCK_FILENAME,
    ArtifactLinkEventCorruptionError as _ArtifactLinkEventCorruptionError,
    ArtifactLinkEventObject as _ArtifactLinkEventObject,
    ArtifactLinkEventPublishError as _ArtifactLinkEventPublishError,
    canonical_artifact_link_event_object as _canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_project import (
    apply_events_to_aggregate as _apply_events_to_aggregate,
    apply_events_to_beads as _apply_events_to_beads,
)
from sase.sdd._artifact_link_store_support import kind_of_ref
from sase.sdd.artifact_link_store import ArtifactLinkStore


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


@dataclass(frozen=True, slots=True)
class _RootPublishReport:
    root_outcomes: tuple[_ArtifactLinkEventRootOutcome, ...]
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()


def publish_artifact_link_events(
    store: ArtifactLinkStore,
    events: Iterable[Mapping[str, Any]],
    *,
    push_after_commit: bool | Literal["async"] | None = "async",
    mutation_origin: str = "machine",
    artifacts_dir: str | Path | None = None,
    already_locked: bool = False,
    extra_roots: Sequence[Path] = (),
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
    if already_locked:
        return _publish_event_objects_locked(
            store,
            objects,
            push_after_commit=push_after_commit,
            mutation_origin=mutation_origin,
            artifacts_dir=artifacts_dir,
            extra_roots=extra_roots,
        )
    with locked_file(lock_path, fcntl.LOCK_EX):
        return _publish_event_objects_locked(
            store,
            objects,
            push_after_commit=push_after_commit,
            mutation_origin=mutation_origin,
            artifacts_dir=artifacts_dir,
            extra_roots=extra_roots,
        )


def _publish_event_objects_locked(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    push_after_commit: bool | Literal["async"] | None,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
    extra_roots: Sequence[Path] = (),
) -> _ArtifactLinkEventPublishReport:
    roots_by_operation = _roots_by_operation(store, objects, extra_roots=extra_roots)
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
    root_outcomes: tuple[_ArtifactLinkEventRootOutcome, ...]
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
            push_after_commit=False,
            verify_publication=False,
            message=ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
        )
        root_outcomes = tuple(
            _ArtifactLinkEventRootOutcome(
                root=root,
                relative_path=item.relative_path,
                created=(root / item.relative_path) in created_paths,
                committed=result.committed,
                durable=_head_contains_event(root, item),
            )
            for item in objects
        )

    publication_error = (
        None
        if push_after_commit is False
        else artifact_link_publication_error_for_roots(
            (root,),
            store=store.sdd_store,
            project_key=store.project_key,
            register_retry=mutation_origin == "machine",
            description=ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
        )
    )
    diagnostics = tuple(
        f"artifact-link event {item.relative_path.as_posix()} is not durable in {root}"
        for item, root_outcome in zip(objects, root_outcomes, strict=True)
        if not root_outcome.durable
    )
    return _RootPublishReport(
        root_outcomes=root_outcomes,
        publication_error=publication_error,
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
    *,
    extra_roots: Sequence[Path] = (),
) -> dict[str, tuple[Path, ...]]:
    forced = tuple(
        dict.fromkeys(root.expanduser().resolve(strict=False) for root in extra_roots)
    )
    roots: dict[str, tuple[Path, ...]] = {}
    for item in objects:
        operation_id = str(item.event["operation_id"])
        roots[operation_id] = tuple(
            dict.fromkeys((*_document_roots_for_event(store, item.event), *forced))
        )
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

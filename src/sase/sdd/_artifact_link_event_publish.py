"""Durable sidecar writes for immutable artifact-link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
from pathlib import Path
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
    ArtifactLinkEventObject as _ArtifactLinkEventObject,
    ArtifactLinkEventPublishError as _ArtifactLinkEventPublishError,
    canonical_artifact_link_event_object as _canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_install import (
    clean_artifact_link_event_staging as _clean_artifact_link_event_staging,
    event_object_is_durable as _event_object_is_durable,
    install_artifact_link_event_object as _install_artifact_link_event_object,
    reject_existing_operation_collisions as _reject_existing_operation_collisions,
)
from sase.sdd._artifact_link_event_local_store import (
    artifact_link_local_event_root as _artifact_link_local_event_root,
    install_local_artifact_link_event as _install_local_artifact_link_event,
    local_artifact_link_event_is_durable as _local_artifact_link_event_is_durable,
)
from sase.sdd._artifact_link_event_ownership import (
    document_kinds_for_store as _document_kinds_for_store,
    event_owner_requirements as _event_owner_requirements,
    publication_evidence as _publication_evidence,
    publication_receipt as _publication_receipt,
    resolved_document_roots_for_store as _resolved_document_roots_for_store,
)
from sase.sdd._artifact_link_event_project import (
    apply_events_to_aggregate as _apply_events_to_aggregate,
    apply_events_to_beads as _apply_events_to_beads,
)
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


@dataclass(slots=True)
class _OperationPublicationState:
    """Mutable receipt state for one canonical event operation."""

    item: _ArtifactLinkEventObject
    requirements: dict[str, Any]
    resolved_roots: dict[str, Path]
    forced_roots: tuple[Path, ...]
    bead_owner: bool
    durable_roots: set[Path]
    local_receipt: bool = False

    @property
    def operation_id(self) -> str:
        return str(self.item.event["operation_id"])


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
    states = _operation_states(store, objects, extra_roots=extra_roots)
    grouped = _objects_by_root_for(states)
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
                digest = root_outcome.path.name[: -len(".json")]
                for state in states.values():
                    if state.item.digest == digest:
                        state.durable_roots.add(root)
                        break

    local_created = _install_local_receipt_events(store, states.values())
    committed = committed or local_created
    for state in states.values():
        if state.local_receipt:
            path = (
                _artifact_link_local_event_root(store.project_key)
                / state.item.relative_path
            )
            event_paths.append(path)
            durable_paths.append(path)

    bead_objects = [
        state.item
        for state in states.values()
        if state.bead_owner and _documents_ready(state)
    ]
    bead_result = _apply_events_to_beads(
        store,
        bead_objects,
        mutation_origin=mutation_origin,
        artifacts_dir=artifacts_dir,
    )
    if bead_result.diagnostic:
        diagnostics.append(
            f"artifact-link bead event publication failed: {bead_result.diagnostic}"
        )

    published_ids = _published_operation_ids(
        states.values(),
        bead_receipt=bead_result.receipt,
        diagnostics=diagnostics,
    )
    ready_objects = [
        state.item for state in states.values() if state.operation_id in published_ids
    ]
    aggregate_rows: tuple[dict[str, Any], ...] = ()
    aggregate_ready = True
    if ready_objects:
        try:
            aggregate_rows = _apply_events_to_aggregate(store, ready_objects)
        except Exception as exc:  # noqa: BLE001 - durable events replay idempotently.
            aggregate_ready = False
            diagnostics.append(f"artifact-link aggregate projection failed: {exc}")

    if not aggregate_ready:
        published_ids = ()
    return _ArtifactLinkEventPublishReport(
        attempted=len(objects),
        published=len(published_ids),
        committed=committed or bead_result.changed,
        event_paths=tuple(dict.fromkeys(event_paths)),
        durable_event_paths=tuple(dict.fromkeys(durable_paths)),
        published_operation_ids=published_ids,
        beads_changed=bead_result.changed,
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
        _clean_artifact_link_event_staging(root)
        _reject_existing_operation_collisions(root, objects)
        for item in objects:
            path = root / item.relative_path
            if _install_artifact_link_event_object(root, item):
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
                durable=_event_object_is_durable(root, item),
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


def _operation_states(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    extra_roots: Sequence[Path] = (),
) -> dict[str, _OperationPublicationState]:
    document_kinds = _document_kinds_for_store(store)
    forced = tuple(
        dict.fromkeys(
            Path(root).expanduser().resolve(strict=False) for root in extra_roots
        )
    )
    states: dict[str, _OperationPublicationState] = {}
    for item in objects:
        operation_id = str(item.event["operation_id"])
        requirements = _event_owner_requirements(item.event, document_kinds)
        bead_refs = requirements.get("bead_refs")
        states[operation_id] = _OperationPublicationState(
            item=item,
            requirements=requirements,
            resolved_roots=_resolved_document_roots_for_store(store, requirements),
            forced_roots=forced,
            bead_owner=bool(bead_refs),
            durable_roots=set(),
        )
    return states


def _objects_by_root_for(
    states: Mapping[str, _OperationPublicationState],
) -> dict[Path, list[_ArtifactLinkEventObject]]:
    grouped: dict[Path, list[_ArtifactLinkEventObject]] = {}
    for state in states.values():
        for root in _required_roots(state):
            resolved = root.expanduser().resolve(strict=False)
            grouped.setdefault(resolved, []).append(state.item)
    return grouped


def _required_roots(state: _OperationPublicationState) -> tuple[Path, ...]:
    return tuple(dict.fromkeys((*state.resolved_roots.values(), *state.forced_roots)))


def _documents_ready(state: _OperationPublicationState) -> bool:
    refs = state.requirements.get("document_refs")
    if isinstance(refs, list):
        for owner in refs:
            if not isinstance(owner, Mapping):
                continue
            kind = str(owner.get("kind") or "")
            if kind and kind not in state.resolved_roots:
                return False
    return all(root in state.durable_roots for root in _required_roots(state))


def _install_local_receipt_events(
    store: ArtifactLinkStore,
    states: Iterable[_OperationPublicationState],
) -> bool:
    created = False
    local_states = [state for state in states if _needs_local_receipt(state)]
    if not local_states:
        return False
    local_root = _artifact_link_local_event_root(store.project_key)
    _reject_existing_operation_collisions(
        local_root,
        [state.item for state in local_states],
    )
    _clean_artifact_link_event_staging(local_root)
    for state in local_states:
        try:
            created = (
                _install_local_artifact_link_event(store.project_key, state.item)
                or created
            )
            state.local_receipt = _local_artifact_link_event_is_durable(
                store.project_key,
                state.item,
            )
        except Exception:
            state.local_receipt = False
    return created


def _needs_local_receipt(state: _OperationPublicationState) -> bool:
    refs = state.requirements.get("document_refs")
    return not refs and not state.forced_roots


def _published_operation_ids(
    states: Iterable[_OperationPublicationState],
    *,
    bead_receipt: bool,
    diagnostics: list[str],
) -> tuple[str, ...]:
    published: list[str] = []
    for state in states:
        receipt = _publication_receipt(
            state.requirements,
            _publication_evidence(
                operation_id=state.operation_id,
                resolved_roots=state.resolved_roots,
                forced_roots=state.forced_roots,
                durable_roots=tuple(state.durable_roots),
                bead_owner=state.bead_owner,
                bead_receipt=state.bead_owner and bead_receipt,
                local_receipt=state.local_receipt,
            ),
        )
        reasons = receipt.get("pending_reasons")
        if isinstance(reasons, list):
            diagnostics.extend(str(reason) for reason in reasons if str(reason))
        if bool(receipt.get("acknowledged")):
            published.append(state.operation_id)
    return tuple(published)


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

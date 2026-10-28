"""Durable sidecar writes for immutable artifact-link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import fcntl
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal

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
    artifact_link_bytes_are_durable as _artifact_link_bytes_are_durable,
    clean_artifact_link_event_staging as _clean_artifact_link_event_staging,
    event_object_is_durable as _event_object_is_durable,
    install_artifact_link_event_object as _install_artifact_link_event_object,
    verify_artifact_link_operation_selection as _verify_operation_selection,
)
from sase.sdd._artifact_link_event_local_store import (
    artifact_link_local_event_root as _artifact_link_local_event_root,
    install_local_artifact_link_event as _install_local_artifact_link_event,
    local_artifact_link_event_is_durable as _local_artifact_link_event_is_durable,
)
from sase.sdd._artifact_link_bead_endpoint import BeadEndpointEvidence
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

if TYPE_CHECKING:
    from sase.sdd._artifact_link_event_quarantine import ArtifactLinkQuarantineFinding


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
class _ParkedPublication:
    """One operation parked after typed bead-endpoint classification."""

    operation_id: str
    digest: str
    reasons: tuple[str, ...]
    endpoints: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _PublicationReceipts:
    """Per-operation acknowledgement, parked, and pending outcomes."""

    acknowledged_ids: tuple[str, ...]
    parked: tuple[_ParkedPublication, ...] = ()
    transient_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ArtifactLinkEventPublishReport:
    """Result of one immutable event publication batch."""

    attempted: int
    published: int = 0
    committed: bool = False
    event_paths: tuple[Path, ...] = ()
    durable_event_paths: tuple[Path, ...] = ()
    published_operation_ids: tuple[str, ...] = ()
    published_event_keys: tuple[tuple[str, str], ...] = ()
    parked_event_keys: tuple[tuple[str, str], ...] = ()
    quarantined_event_keys: tuple[tuple[str, str], ...] = ()
    quarantine_findings: tuple[ArtifactLinkQuarantineFinding, ...] = ()
    quarantine_paths: tuple[Path, ...] = ()
    parked_operations: tuple[_ParkedPublication, ...] = ()
    transient_operation_ids: tuple[str, ...] = ()
    beads_changed: bool = False
    aggregate_rows: tuple[dict[str, Any], ...] = ()
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()
    deferred: bool = False
    bead_projection_failed: bool = False


@dataclass(frozen=True, slots=True)
class _RootPublishReport:
    root_outcomes: tuple[_ArtifactLinkEventRootOutcome, ...]
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _QuarantinePersistReport:
    event_keys: tuple[tuple[str, str], ...] = ()
    findings: tuple[ArtifactLinkQuarantineFinding, ...] = ()
    paths: tuple[Path, ...] = ()
    committed: bool = False
    diagnostics: tuple[str, ...] = ()
    publication_errors: tuple[str, ...] = ()


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

    @property
    def event_key(self) -> tuple[str, str]:
        return self.operation_id, self.item.digest


def publish_artifact_link_events(
    store: ArtifactLinkStore,
    events: Iterable[Mapping[str, Any]],
    *,
    push_after_commit: bool | Literal["async"] | None = "async",
    mutation_origin: str = "machine",
    artifacts_dir: str | Path | None = None,
    already_locked: bool = False,
    extra_roots: Sequence[Path] = (),
    deadline: float | None = None,
) -> _ArtifactLinkEventPublishReport:
    """Publish immutable link events and update local non-durable projections."""

    objects = _unique_event_objects(
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
            deadline=deadline,
        )
    with locked_file(lock_path, fcntl.LOCK_EX):
        return _publish_event_objects_locked(
            store,
            objects,
            push_after_commit=push_after_commit,
            mutation_origin=mutation_origin,
            artifacts_dir=artifacts_dir,
            extra_roots=extra_roots,
            deadline=deadline,
        )


def _publish_event_objects_locked(
    store: ArtifactLinkStore,
    objects: Sequence[_ArtifactLinkEventObject],
    *,
    push_after_commit: bool | Literal["async"] | None,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
    extra_roots: Sequence[Path] = (),
    deadline: float | None = None,
) -> _ArtifactLinkEventPublishReport:
    from sase.sdd._artifact_link_event_project import (
        BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
    )
    from sase.sdd._artifact_link_event_collision import (
        candidate_from_event as _candidate_from_event,
        partition_artifact_link_candidates as _partition_candidates,
    )
    from sase.sdd._artifact_link_event_quarantine import (
        ArtifactLinkQuarantineFinding,
        persist_artifact_link_quarantine_record,
    )

    if deadline is not None and time.monotonic() >= deadline:
        return _ArtifactLinkEventPublishReport(
            attempted=len(objects),
            skip_diagnostics=(BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,),
            deferred=True,
        )
    # Include pending outbox events so an older queued payload beats a newer
    # incoming replay. The Rust partition runs under the project publication
    # lock and before any root write or projection.
    snapshot = store.artifact_link_event_snapshot(
        include_pending=True,
        strict=True,
    )
    input_digests = {item.digest for item in objects}
    incoming_candidates = tuple(
        _candidate_from_event(
            item.event,
            tier="incoming",
            source_locator=f"incoming:{item.event['operation_id']}",
            digest=item.digest,
            canonical_json=item.canonical_json,
        )
        for item in objects
    )
    partition = _partition_candidates((*snapshot.candidates, *incoming_candidates))
    accepted_digests = {item.digest for item in partition.accepted}
    accepted_objects = tuple(
        item for item in objects if item.digest in accepted_digests
    )
    findings_by_digest = {
        finding.rejected_digest: finding
        for finding in partition.findings
        if finding.rejected_digest in input_digests
    }
    rejected_objects = tuple(
        item for item in objects if item.digest not in accepted_digests
    )
    findings_by_key: dict[tuple[str, str], ArtifactLinkQuarantineFinding] = {}
    for item in rejected_objects:
        finding = findings_by_digest.get(item.digest)
        if finding is None:
            raise RuntimeError(
                "artifact-link collision partition rejected an input without a finding"
            )
        findings_by_key[(str(item.event["operation_id"]), item.digest)] = finding

    quarantine = _persist_incoming_quarantine_findings(
        store,
        findings_by_key,
        objects=objects,
        candidates=snapshot.candidates,
        extra_roots=extra_roots,
        mutation_origin=mutation_origin,
        push_after_commit=push_after_commit,
        artifacts_dir=artifacts_dir,
        persist=persist_artifact_link_quarantine_record,
        canonical_event_object=_canonical_artifact_link_event_object,
        is_durable=_artifact_link_bytes_are_durable,
    )
    if not accepted_objects:
        quarantine_diagnostics = [*quarantine.diagnostics]
        quarantine_diagnostics.extend(
            finding.render() for finding in quarantine.findings
        )
        return _ArtifactLinkEventPublishReport(
            attempted=len(objects),
            committed=quarantine.committed,
            quarantined_event_keys=quarantine.event_keys,
            quarantine_findings=quarantine.findings,
            quarantine_paths=quarantine.paths,
            publication_error="\n".join(quarantine.publication_errors) or None,
            skip_diagnostics=tuple(dict.fromkeys(quarantine_diagnostics)),
        )

    states = _operation_states(
        store,
        accepted_objects,
        extra_roots=extra_roots,
    )
    grouped = _objects_by_root_for(states)
    event_paths: list[Path] = []
    durable_paths: list[Path] = []
    diagnostics: list[str] = list(quarantine.diagnostics)
    diagnostics.extend(finding.render() for finding in quarantine.findings)
    publication_errors: list[str] = list(quarantine.publication_errors)
    committed = quarantine.committed

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
        if _documents_ready(state)
        and (
            state.bead_owner
            or (
                store.beads_dir is not None
                and _event_can_affect_bead_projections(state.item.event)
            )
        )
    ]
    bead_result = _apply_events_to_beads(
        store,
        bead_objects,
        mutation_origin=mutation_origin,
        artifacts_dir=artifacts_dir,
        deadline=deadline,
    )
    if bead_result.deferred:
        diagnostics.append(
            f"artifact-link bead projection {bead_result.diagnostic}"
            if bead_result.diagnostic
            else f"artifact-link bead projection {BEAD_PROJECTION_DEFERRED_DIAGNOSTIC}"
        )
    elif bead_result.diagnostic:
        diagnostics.append(
            f"artifact-link bead event publication failed: {bead_result.diagnostic}"
        )

    receipts = _published_operation_ids(
        states.values(),
        bead_receipt=bead_result.receipt,
        diagnostics=diagnostics,
        beads_available=store.beads_dir is not None,
        endpoint_evidence=bead_result.endpoint_evidence,
    )
    published_ids = receipts.acknowledged_ids
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
    published_event_keys = tuple(
        state.event_key
        for state in states.values()
        if state.operation_id in published_ids
    )
    parked_event_keys = tuple(
        (item.operation_id, item.digest) for item in receipts.parked
    )
    return _ArtifactLinkEventPublishReport(
        attempted=len(objects),
        published=len(published_ids),
        committed=committed or bead_result.changed,
        event_paths=tuple(dict.fromkeys(event_paths)),
        durable_event_paths=tuple(dict.fromkeys(durable_paths)),
        published_operation_ids=published_ids,
        published_event_keys=published_event_keys,
        parked_event_keys=parked_event_keys,
        quarantined_event_keys=quarantine.event_keys,
        quarantine_findings=quarantine.findings,
        quarantine_paths=quarantine.paths,
        parked_operations=receipts.parked,
        transient_operation_ids=receipts.transient_ids,
        beads_changed=bead_result.changed,
        aggregate_rows=aggregate_rows,
        publication_error="\n".join(publication_errors) or None,
        skip_diagnostics=tuple(dict.fromkeys(diagnostics)),
        deferred=bead_result.deferred,
        bead_projection_failed=bool(bead_result.failed),
    )


def _persist_incoming_quarantine_findings(
    store: ArtifactLinkStore,
    findings_by_key: Mapping[tuple[str, str], Any],
    *,
    objects: Sequence[_ArtifactLinkEventObject],
    candidates: Sequence[Any],
    extra_roots: Sequence[Path],
    mutation_origin: str,
    push_after_commit: bool | Literal["async"] | None,
    artifacts_dir: str | Path | None,
    persist: Any,
    canonical_event_object: Any,
    is_durable: Any,
) -> _QuarantinePersistReport:
    """Persist rejected bytes before reporting them settled to the outbox."""

    from sase.sdd._artifact_link_commit import (
        artifact_link_publication_error_for_roots,
        commit_artifact_link_indexes,
    )
    from sase.sdd._artifact_link_event_local_store import (
        artifact_link_local_event_root,
    )
    from sase.sdd._git_contention import store_git_write_lock

    if not findings_by_key:
        return _QuarantinePersistReport()

    local_root = artifact_link_local_event_root(store.project_key).resolve(strict=False)
    all_states = _operation_states(store, objects, extra_roots=extra_roots)
    roots_by_key: dict[tuple[str, str], set[Path]] = {}
    findings_by_root: dict[Path, list[tuple[tuple[str, str], Any]]] = {}
    for event_key, finding in findings_by_key.items():
        _, digest = event_key
        roots: set[Path] = set()
        state = all_states.get(digest)
        if state is not None:
            roots.update(_required_roots(state))
        roots.update(
            Path(str(candidate.root)).expanduser().resolve(strict=False)
            for candidate in candidates
            if getattr(candidate, "digest", None) == digest
            and getattr(candidate, "root", None)
        )
        if not roots:
            roots.add(local_root)
        roots_by_key[event_key] = roots
        for root in roots:
            findings_by_root.setdefault(root, []).append((event_key, finding))

    persisted_roots: dict[tuple[str, str], set[Path]] = {
        key: set() for key in findings_by_key
    }
    relative_by_key: dict[tuple[str, str], str] = {}
    paths: list[Path] = []
    diagnostics: list[str] = []
    publication_errors: list[str] = []
    committed = False

    def persist_at_root(
        root: Path, entries: Sequence[tuple[tuple[str, str], Any]]
    ) -> None:
        nonlocal committed
        installed: list[tuple[tuple[str, str], Any, str, Path, bytes]] = []
        for event_key, finding in entries:
            try:
                rejected = canonical_event_object(finding.rejected_event)
                relative = str(
                    persist(
                        root,
                        finding,
                        rejected_canonical_json=rejected.canonical_json,
                    )
                )
                record_path = root / relative
                installed.append(
                    (
                        event_key,
                        finding,
                        relative,
                        record_path,
                        record_path.read_bytes(),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - retry leaves the outbox row.
                diagnostics.append(
                    f"could not persist artifact-link quarantine for "
                    f"{event_key[0]}:{event_key[1]} in {root}: {exc}"
                )
        if not installed:
            return

        if root != local_root:
            try:
                result = commit_artifact_link_indexes(
                    [],
                    store=store.sdd_store,
                    project_key=store.project_key,
                    repo_roots=(root,),
                    artifacts_dir=artifacts_dir,
                    already_locked=True,
                    mutation_origin=mutation_origin,
                    push_after_commit=False,
                    verify_publication=False,
                    extra_paths_by_root={
                        root: [record_path for _, _, _, record_path, _ in installed]
                    },
                    message=ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
                )
                committed = committed or result.committed
            except Exception as exc:  # noqa: BLE001 - retry from the durable outbox.
                diagnostics.extend(
                    f"could not commit artifact-link quarantine for "
                    f"{event_key[0]}:{event_key[1]} in {root}: {exc}"
                    for event_key, *_ in installed
                )
                return

        for event_key, finding, relative, record_path, payload in installed:
            if not is_durable(root, relative, payload):
                diagnostics.append(
                    f"artifact-link quarantine is not durable for "
                    f"{event_key[0]}:{event_key[1]} in {root}"
                )
                continue
            persisted_roots[event_key].add(root)
            relative_by_key[event_key] = relative
            paths.append(record_path)

        if root != local_root and push_after_commit is not False:
            publication_error = artifact_link_publication_error_for_roots(
                (root,),
                store=store.sdd_store,
                project_key=store.project_key,
                register_retry=mutation_origin == "machine",
                description=ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
            )
            if publication_error:
                publication_errors.append(publication_error)

    for root, entries in sorted(
        findings_by_root.items(), key=lambda item: item[0].as_posix()
    ):
        if root == local_root:
            persist_at_root(root, entries)
            continue
        with store_git_write_lock(
            root,
            op="artifact_link.event_quarantine",
            mutates_worktree=True,
        ) as acquired:
            if not acquired:
                diagnostics.extend(
                    f"could not acquire quarantine write lock for "
                    f"{event_key[0]}:{event_key[1]} in {root}"
                    for event_key, _ in entries
                )
                continue
            persist_at_root(root, entries)

    successful_keys = tuple(
        key
        for key, required_roots in roots_by_key.items()
        if required_roots and required_roots.issubset(persisted_roots[key])
    )
    report_findings = tuple(
        replace(findings_by_key[key], record_path=relative_by_key[key])
        for key in successful_keys
        if key in relative_by_key
    )
    return _QuarantinePersistReport(
        event_keys=successful_keys,
        findings=report_findings,
        paths=tuple(dict.fromkeys(paths)),
        committed=committed,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        publication_errors=tuple(dict.fromkeys(publication_errors)),
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
        _verify_operation_selection(root, objects)
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
        requirements = _event_owner_requirements(item.event, document_kinds)
        bead_refs = requirements.get("bead_refs")
        states[item.digest] = _OperationPublicationState(
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


def _event_can_affect_bead_projections(event: Mapping[str, Any]) -> bool:
    kind = event.get("kind")
    return isinstance(kind, dict) and str(kind.get("type") or "") == "alias"


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
    _verify_operation_selection(
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
    beads_available: bool = False,
    endpoint_evidence: Sequence[BeadEndpointEvidence] = (),
) -> _PublicationReceipts:
    by_operation: dict[str, dict[str, BeadEndpointEvidence]] = {}
    for item in endpoint_evidence:
        by_operation.setdefault(item.operation_id, {})[item.issue_id] = item
    published: list[str] = []
    parked: list[_ParkedPublication] = []
    transient_ids: list[str] = []
    for state in states:
        needs_bead = state.bead_owner or (
            beads_available and _event_can_affect_bead_projections(state.item.event)
        )
        bead_refs = state.requirements.get("bead_refs")
        endpoints = (
            _bead_endpoint_wires(
                state.operation_id,
                bead_refs,
                by_operation.get(state.operation_id, {}),
            )
            if needs_bead
            else None
        )
        receipt = _publication_receipt(
            state.requirements,
            _publication_evidence(
                operation_id=state.operation_id,
                resolved_roots=state.resolved_roots,
                forced_roots=state.forced_roots,
                durable_roots=tuple(state.durable_roots),
                bead_owner=needs_bead,
                bead_receipt=needs_bead and bead_receipt,
                local_receipt=state.local_receipt,
                bead_endpoints=endpoints,
            ),
        )
        reasons = tuple(
            str(reason)
            for reason in (receipt.get("pending_reasons") or ())
            if str(reason)
        )
        disposition = str(receipt.get("disposition") or "")
        # `acknowledged` is the drain-from-outbox signal. Additive
        # `disposition` classifies parked vs pending when that flag is false.
        if bool(receipt.get("acknowledged")):
            published.append(state.operation_id)
            continue
        if disposition == "parked":
            parked.append(
                _ParkedPublication(
                    operation_id=state.operation_id,
                    digest=state.item.digest,
                    reasons=reasons,
                    endpoints=tuple(endpoints or ()),
                )
            )
            continue
        diagnostics.extend(reasons)
        if _endpoints_include_transient(endpoints):
            transient_ids.append(state.operation_id)
    return _PublicationReceipts(
        acknowledged_ids=tuple(published),
        parked=tuple(parked),
        transient_ids=tuple(dict.fromkeys(transient_ids)),
    )


def _endpoints_include_transient(endpoints: list[dict[str, Any]] | None) -> bool:
    if not endpoints:
        return False
    for item in endpoints:
        outcome = item.get("outcome")
        if outcome == "transient":
            return True
        if isinstance(outcome, Mapping) and "transient" in outcome:
            return True
    return False


def _bead_endpoint_wires(
    operation_id: str,
    bead_refs: object,
    by_issue: Mapping[str, BeadEndpointEvidence],
) -> list[dict[str, Any]] | None:
    from sase.sdd.artifact_link_beads import bead_id_from_ref

    if not isinstance(bead_refs, list) or not bead_refs:
        return None
    endpoints: list[dict[str, Any]] = []
    for raw_ref in bead_refs:
        issue_id = bead_id_from_ref(str(raw_ref)) or str(raw_ref).removeprefix("bead:")
        if not issue_id:
            continue
        item = by_issue.get(issue_id)
        if item is None:
            item = BeadEndpointEvidence(
                operation_id=operation_id,
                issue_id=issue_id,
                outcome="transient",
                detail="missing_evidence",
            )
        endpoints.append(item.to_wire())
    return endpoints


def _unique_event_objects(
    objects: Iterable[_ArtifactLinkEventObject],
) -> tuple[_ArtifactLinkEventObject, ...]:
    by_digest: dict[str, _ArtifactLinkEventObject] = {}
    order: list[str] = []
    for item in objects:
        digest = item.digest
        existing = by_digest.get(digest)
        if existing is not None:
            if existing.canonical_json != item.canonical_json:
                raise _ArtifactLinkEventPublishError(
                    f"artifact-link event digest collision for `{digest}`"
                )
            continue
        by_digest[digest] = item
        order.append(digest)
    return tuple(by_digest[digest] for digest in order)

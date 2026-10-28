"""Durable sidecar, quarantine, and local-receipt writes for link events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sase.sdd._artifact_link_commit import (
    artifact_link_publication_error_for_roots,
    commit_artifact_link_indexes,
)
from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_COMMIT_MESSAGE,
    ArtifactLinkEventObject,
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_collision import (
    candidate_from_event,
    partition_artifact_link_candidates,
)
from sase.sdd._artifact_link_event_install import (
    artifact_link_bytes_are_durable,
    clean_artifact_link_event_staging,
    event_object_is_durable,
    install_artifact_link_event_object,
    verify_artifact_link_operation_selection,
)
from sase.sdd._artifact_link_event_local_store import (
    artifact_link_local_event_root,
    install_local_artifact_link_event,
    local_artifact_link_event_is_durable,
)
from sase.sdd._artifact_link_event_publish_state import (
    OperationPublicationState,
    operation_states,
    required_roots,
)
from sase.sdd._artifact_link_event_quarantine import (
    ArtifactLinkQuarantineFinding,
    persist_artifact_link_quarantine_record,
)
from sase.sdd._git_contention import store_git_write_lock
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


@dataclass(frozen=True, slots=True)
class _IncomingEventAdmission:
    accepted_objects: tuple[ArtifactLinkEventObject, ...]
    quarantine: _QuarantinePersistReport


def admit_incoming_event_objects(
    store: ArtifactLinkStore,
    objects: Sequence[ArtifactLinkEventObject],
    *,
    extra_roots: Sequence[Path],
    mutation_origin: str,
    push_after_commit: bool | Literal["async"] | None,
    artifacts_dir: str | Path | None,
) -> _IncomingEventAdmission:
    """Partition incoming events and persist quarantine for rejected digests."""

    # Include pending outbox events so an older queued payload beats a newer
    # incoming replay. The Rust partition runs under the project publication
    # lock and before any root write or projection.
    snapshot = store.artifact_link_event_snapshot(
        include_pending=True,
        strict=True,
    )
    input_digests = {item.digest for item in objects}
    incoming_candidates = tuple(
        candidate_from_event(
            item.event,
            tier="incoming",
            source_locator=f"incoming:{item.event['operation_id']}",
            digest=item.digest,
            canonical_json=item.canonical_json,
        )
        for item in objects
    )
    partition = partition_artifact_link_candidates(
        (*snapshot.candidates, *incoming_candidates)
    )
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

    return _IncomingEventAdmission(
        accepted_objects=accepted_objects,
        quarantine=_persist_incoming_quarantine_findings(
            store,
            findings_by_key,
            objects=objects,
            candidates=snapshot.candidates,
            extra_roots=extra_roots,
            mutation_origin=mutation_origin,
            push_after_commit=push_after_commit,
            artifacts_dir=artifacts_dir,
        ),
    )


def _persist_incoming_quarantine_findings(
    store: ArtifactLinkStore,
    findings_by_key: Mapping[tuple[str, str], Any],
    *,
    objects: Sequence[ArtifactLinkEventObject],
    candidates: Sequence[Any],
    extra_roots: Sequence[Path],
    mutation_origin: str,
    push_after_commit: bool | Literal["async"] | None,
    artifacts_dir: str | Path | None,
) -> _QuarantinePersistReport:
    """Persist rejected bytes before reporting them settled to the outbox."""

    if not findings_by_key:
        return _QuarantinePersistReport()

    local_root = artifact_link_local_event_root(store.project_key).resolve(strict=False)
    all_states = operation_states(store, objects, extra_roots=extra_roots)
    roots_by_key: dict[tuple[str, str], set[Path]] = {}
    findings_by_root: dict[Path, list[tuple[tuple[str, str], Any]]] = {}
    for event_key, finding in findings_by_key.items():
        _, digest = event_key
        roots: set[Path] = set()
        state = all_states.get(digest)
        if state is not None:
            roots.update(required_roots(state))
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
                rejected = canonical_artifact_link_event_object(finding.rejected_event)
                relative = str(
                    persist_artifact_link_quarantine_record(
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
            if not artifact_link_bytes_are_durable(root, relative, payload):
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
        for key, needed_roots in roots_by_key.items()
        if needed_roots and needed_roots.issubset(persisted_roots[key])
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


def publish_root_events(
    store: ArtifactLinkStore,
    root: Path,
    objects: Sequence[ArtifactLinkEventObject],
    *,
    push_after_commit: bool | Literal["async"] | None,
    mutation_origin: str,
    artifacts_dir: str | Path | None,
) -> _RootPublishReport:
    """Install and commit *objects* under one sidecar *root*."""

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
        clean_artifact_link_event_staging(root)
        verify_artifact_link_operation_selection(root, objects)
        for item in objects:
            path = root / item.relative_path
            if install_artifact_link_event_object(root, item):
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
                durable=event_object_is_durable(root, item),
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


def install_local_receipt_events(
    store: ArtifactLinkStore,
    states: Iterable[OperationPublicationState],
) -> bool:
    """Install ownerless events into the machine-local durable event root."""

    created = False
    local_states = [state for state in states if _needs_local_receipt(state)]
    if not local_states:
        return False
    local_root = artifact_link_local_event_root(store.project_key)
    verify_artifact_link_operation_selection(
        local_root,
        [state.item for state in local_states],
    )
    clean_artifact_link_event_staging(local_root)
    for state in local_states:
        try:
            created = (
                install_local_artifact_link_event(store.project_key, state.item)
                or created
            )
            state.local_receipt = local_artifact_link_event_is_durable(
                store.project_key,
                state.item,
            )
        except Exception:
            state.local_receipt = False
    return created


def _needs_local_receipt(state: OperationPublicationState) -> bool:
    refs = state.requirements.get("document_refs")
    return not refs and not state.forced_roots


__all__ = [
    "admit_incoming_event_objects",
    "install_local_receipt_events",
    "publish_root_events",
]

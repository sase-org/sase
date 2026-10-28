"""Publish immutable artifact-link events and update local projections.

Durable root writes, collision admission, and quarantine persistence live in
sibling modules so this file can keep the lock, projection, and receipt
orchestration.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal

from sase.core.paths import sase_projects_dir
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_bead_endpoint import BeadEndpointEvidence
from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_LOCK_FILENAME,
    ArtifactLinkEventObject as _ArtifactLinkEventObject,
    ArtifactLinkEventPublishError as _ArtifactLinkEventPublishError,
    canonical_artifact_link_event_object as _canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_local_store import (
    artifact_link_local_event_root as _artifact_link_local_event_root,
)
from sase.sdd._artifact_link_event_ownership import (
    publication_evidence as _publication_evidence,
    publication_receipt as _publication_receipt,
)
from sase.sdd._artifact_link_event_project import (
    BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
    apply_events_to_aggregate as _apply_events_to_aggregate,
    apply_events_to_beads as _apply_events_to_beads,
)
from sase.sdd._artifact_link_event_publish_persist import (
    admit_incoming_event_objects as _admit_incoming_event_objects,
    install_local_receipt_events as _install_local_receipt_events,
    publish_root_events as _publish_root_events,
)
from sase.sdd._artifact_link_event_publish_state import (
    OperationPublicationState as _OperationPublicationState,
    operation_states as _operation_states,
    required_roots as _required_roots,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore

if TYPE_CHECKING:
    from sase.sdd._artifact_link_event_quarantine import ArtifactLinkQuarantineFinding


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
    if deadline is not None and time.monotonic() >= deadline:
        return _ArtifactLinkEventPublishReport(
            attempted=len(objects),
            skip_diagnostics=(BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,),
            deferred=True,
        )
    admission = _admit_incoming_event_objects(
        store,
        objects,
        extra_roots=extra_roots,
        mutation_origin=mutation_origin,
        push_after_commit=push_after_commit,
        artifacts_dir=artifacts_dir,
    )
    accepted_objects = admission.accepted_objects
    quarantine = admission.quarantine
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


def _objects_by_root_for(
    states: Mapping[str, _OperationPublicationState],
) -> dict[Path, list[_ArtifactLinkEventObject]]:
    grouped: dict[Path, list[_ArtifactLinkEventObject]] = {}
    for state in states.values():
        for root in _required_roots(state):
            resolved = root.expanduser().resolve(strict=False)
            grouped.setdefault(resolved, []).append(state.item)
    return grouped


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


__all__ = ["publish_artifact_link_events"]

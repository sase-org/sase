"""Event, publication, and cutover health signals for link doctor."""

from __future__ import annotations

from dataclasses import dataclass

from sase.sdd._artifact_link_cutover_state import inspect_artifact_link_cutover_markers
from sase.sdd._artifact_link_publication_retry import (
    ArtifactLinkPublicationRetryDetail,
    inspect_artifact_link_publications,
)
from sase.sdd.artifact_link_import_indexes import (
    artifact_link_legacy_links_tree_identity,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore


@dataclass(frozen=True)
class _EventHealthValues:
    event_objects: int = 0
    event_pending: int = 0
    event_pending_oldest_age_seconds: float = 0.0
    event_pending_p95_age_seconds: float = 0.0
    event_validation_failures: tuple[str, ...] = ()
    event_reduction_errors: tuple[str, ...] = ()
    event_orphaned_tombstones: tuple[str, ...] = ()


def event_health_values(store: ArtifactLinkStore) -> _EventHealthValues:
    snapshot = getattr(store, "artifact_link_event_snapshot", None)
    if not callable(snapshot):
        return _EventHealthValues()
    try:
        event_snapshot = snapshot(strict=False)
    except Exception as exc:  # noqa: BLE001 - event diagnostics should be visible.
        return _EventHealthValues(event_reduction_errors=(str(exc),))
    return _EventHealthValues(
        event_objects=event_snapshot.durable_event_count,
        event_pending=event_snapshot.pending_event_count,
        event_pending_oldest_age_seconds=(
            event_snapshot.pending_stats.oldest_age_seconds
        ),
        event_pending_p95_age_seconds=event_snapshot.pending_stats.p95_age_seconds,
        event_validation_failures=tuple(
            finding.render() for finding in event_snapshot.validation_findings
        ),
        event_reduction_errors=event_snapshot.reduction_errors,
        event_orphaned_tombstones=event_snapshot.orphaned_tombstones,
    )


@dataclass(frozen=True)
class _PublicationHealthValues:
    publication_pending: tuple[str, ...] = ()
    publication_aged: tuple[str, ...] = ()
    publication_diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class _CutoverHealthValues:
    cutover_state: str = "none"
    cutover_errors: tuple[str, ...] = ()
    cutover_stragglers: tuple[str, ...] = ()


def publication_health_values(store: ArtifactLinkStore) -> _PublicationHealthValues:
    if not isinstance(store, ArtifactLinkStore):
        return _PublicationHealthValues()
    try:
        inspection = inspect_artifact_link_publications(store.project_key)
    except Exception as exc:  # noqa: BLE001 - doctor should report, not crash.
        return _PublicationHealthValues(publication_diagnostics=(str(exc),))
    pending = tuple(
        _publication_detail_text(detail)
        for detail in inspection.details
        if detail.status != "aged"
    )
    aged = tuple(
        _publication_detail_text(detail)
        for detail in inspection.details
        if detail.status == "aged"
    )
    return _PublicationHealthValues(
        publication_pending=pending,
        publication_aged=aged,
        publication_diagnostics=inspection.diagnostics,
    )


def cutover_health_values(store: ArtifactLinkStore) -> _CutoverHealthValues:
    if not isinstance(store, ArtifactLinkStore):
        return _CutoverHealthValues()
    try:
        inspection = inspect_artifact_link_cutover_markers(
            store.sidecar_roots,
            project_key=store.project_key,
        )
    except Exception as exc:  # noqa: BLE001 - doctor should report, not crash.
        return _CutoverHealthValues(cutover_state="invalid", cutover_errors=(str(exc),))
    if inspection.marker is None:
        return _CutoverHealthValues(cutover_state="none")
    if inspection.state == "incomplete":
        diagnostics = inspection.diagnostics or (
            "resume with `sase artifact link import-indexes --apply <attestation>`",
        )
        return _CutoverHealthValues(
            cutover_state="incomplete",
            cutover_errors=tuple(diagnostics),
        )
    stragglers: list[str] = []
    if inspection.imported:
        for role in inspection.marker.roles:
            root = store.sidecar_roots.get(role.kind)
            if root is None:
                continue
            current = artifact_link_legacy_links_tree_identity(root)
            if current != role.links_tree:
                stragglers.append(
                    f"{role.role}: links/ tree {current} != frozen {role.links_tree}"
                )
    return _CutoverHealthValues(
        cutover_state=inspection.state,
        cutover_stragglers=tuple(stragglers),
    )


def _publication_detail_text(detail: ArtifactLinkPublicationRetryDetail) -> str:
    text = (
        f"{detail.project_key}/{detail.role}: "
        f"{detail.repo_root} ({round(detail.age_seconds)}s)"
    )
    if detail.last_error:
        text += f" - {detail.last_error}"
    return text


__all__ = [
    "cutover_health_values",
    "event_health_values",
    "publication_health_values",
]

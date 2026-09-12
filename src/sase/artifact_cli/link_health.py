"""Link-graph health for ``sase artifact doctor``."""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.artifact_cli._link_health_coverage import (
    ArtifactLinkCoverageReport,
    coverage_report,
    read_row_count,
)
from sase.artifact_cli._link_health_indexes import (
    missing_head_indexes,
    orphaned_link_indexes,
)
from sase.artifact_cli._link_health_projections import rebuild_existing_projections
from sase.artifact_cli._link_health_refs import dangling_refs
from sase.artifact_cli._link_health_signals import (
    cutover_health_values,
    event_health_values,
    publication_health_values,
)
from sase.artifact_cli._link_health_tables import missing_companions, stale_tables
from sase.artifact_cli.references import resolve_cli_reference
from sase.artifact_read_log import read_artifact_read_events
from sase.artifact_refs import launch_artifact_ref_context
from sase.sdd._artifact_link_renames import repair_historical_artifact_renames
from sase.sdd._artifact_link_store_support import store_backed_rows
from sase.sdd.artifact_link_drift import (
    ArtifactLinkIndexDrift,
    build_artifact_link_index_drift,
)
from sase.sdd.artifact_link_outbox import inspect_artifact_link_outbox
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    resolve_artifact_link_store,
)


@dataclass(frozen=True)
class ArtifactLinkHealthReport:
    """Doctor findings for the artifact link graph."""

    skipped: bool
    dangling: tuple[str, ...] = ()
    unpublished_agent_refs: tuple[str, ...] = ()
    stale_tables: tuple[str, ...] = ()
    missing_companions: tuple[str, ...] = ()
    orphaned_companions: tuple[str, ...] = ()
    missing_head_indexes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    read_events: int = 0
    recorded_read_events: int = 0
    durable_read_rows: int = 0
    durable_store_rows: int = 0
    durable_sidecar_rows: int = 0
    aggregate_rows: int = 0
    expected_index_rows: int = 0
    aggregate_drift: ArtifactLinkIndexDrift = field(
        default_factory=ArtifactLinkIndexDrift
    )
    outbox_entries: int = 0
    outbox_event_entries: int = 0
    outbox_legacy_entries: int = 0
    outbox_invalid_entries: int = 0
    outbox_dropped: int = 0
    outbox_oldest_age_seconds: float = 0.0
    outbox_p95_age_seconds: float = 0.0
    event_objects: int = 0
    event_pending: int = 0
    event_pending_oldest_age_seconds: float = 0.0
    event_pending_p95_age_seconds: float = 0.0
    event_validation_failures: tuple[str, ...] = ()
    event_reduction_errors: tuple[str, ...] = ()
    event_orphaned_tombstones: tuple[str, ...] = ()
    publication_pending: tuple[str, ...] = ()
    publication_aged: tuple[str, ...] = ()
    publication_diagnostics: tuple[str, ...] = ()
    cutover_state: str = "none"
    cutover_errors: tuple[str, ...] = ()
    cutover_stragglers: tuple[str, ...] = ()
    coverage: ArtifactLinkCoverageReport = field(
        default_factory=ArtifactLinkCoverageReport
    )
    rebuilt: bool = False
    repaired_renames: int = 0

    @property
    def healthy(self) -> bool:
        if self.skipped:
            return True
        return not any(
            (
                self.dangling,
                self.stale_tables,
                self.missing_companions,
                self.orphaned_companions,
                self.missing_head_indexes,
                self.errors,
                self.event_validation_failures,
                self.event_reduction_errors,
                self.event_orphaned_tombstones,
                self.publication_aged,
                self.publication_diagnostics,
                self.cutover_errors,
                self.cutover_stragglers,
                self.aggregate_drift.has_drift,
            )
        )


def inspect_artifact_link_health(*, fix: bool = False) -> ArtifactLinkHealthReport:
    """Inspect (and optionally rebuild) the current project's link graph."""

    try:
        store = resolve_artifact_link_store()
    except Exception as exc:  # noqa: BLE001 - report the file index too
        return ArtifactLinkHealthReport(skipped=False, errors=(str(exc),))

    event_health = event_health_values(store)
    publication_health = publication_health_values(store)
    cutover_health = cutover_health_values(store)
    try:
        if fix:
            store.reconcile_aggregate()
        aggregate = store.load_aggregate()
        expected = store.preview_aggregate()
        aggregate_rows = list(aggregate.get("rows", []))
        expected_rows = list(expected.get("rows", []))
        drift = build_artifact_link_index_drift(
            expected_rows=expected_rows,
            indexed_rows=aggregate_rows,
        )
        rows = store_backed_rows(expected_rows)
        durable_rows = store.load_durable_rows()
        sidecar_rows = store.durable_sidecar_rows()
    except Exception as exc:  # noqa: BLE001 - surface unsupported v1/schema errors
        return ArtifactLinkHealthReport(
            skipped=False,
            errors=(str(exc),),
            event_objects=event_health.event_objects,
            event_pending=event_health.event_pending,
            event_pending_oldest_age_seconds=(
                event_health.event_pending_oldest_age_seconds
            ),
            event_pending_p95_age_seconds=event_health.event_pending_p95_age_seconds,
            event_validation_failures=event_health.event_validation_failures,
            event_reduction_errors=event_health.event_reduction_errors,
            event_orphaned_tombstones=event_health.event_orphaned_tombstones,
            publication_pending=publication_health.publication_pending,
            publication_aged=publication_health.publication_aged,
            publication_diagnostics=publication_health.publication_diagnostics,
            cutover_state=cutover_health.cutover_state,
            cutover_errors=cutover_health.cutover_errors,
            cutover_stragglers=cutover_health.cutover_stragglers,
        )
    resolution_context = launch_artifact_ref_context(is_home_mode=False)
    dangling, unpublished_agents = dangling_refs(
        rows,
        store,
        context=resolution_context,
        resolve_reference=resolve_cli_reference,
    )
    orphaned_companions = orphaned_link_indexes(store)
    repaired_renames = 0
    if fix:
        repair = repair_historical_artifact_renames(
            store,
            (*dangling, *orphaned_companions),
        )
        repaired_renames = len(repair.renames) if repair.changed else 0
        if repair.changed:
            try:
                rows = store_backed_rows(store.load_aggregate().get("rows", []))
                sidecar_rows = store.durable_sidecar_rows()
                dangling, unpublished_agents = dangling_refs(
                    rows,
                    store,
                    context=resolution_context,
                    resolve_reference=resolve_cli_reference,
                )
                orphaned_companions = orphaned_link_indexes(store)
            except Exception as exc:  # noqa: BLE001 - report the failed repair.
                return ArtifactLinkHealthReport(skipped=False, errors=(str(exc),))
        aggregate = store.load_aggregate()
        expected = store.preview_aggregate()
        aggregate_rows = list(aggregate.get("rows", []))
        expected_rows = list(expected.get("rows", []))
        drift = build_artifact_link_index_drift(
            expected_rows=expected_rows,
            indexed_rows=aggregate_rows,
        )
        rows = store_backed_rows(expected_rows)
        durable_rows = store.load_durable_rows()
    stale = stale_tables(store, rows)
    missing = missing_companions(
        rows,
        context=resolution_context,
        resolve_reference=resolve_cli_reference,
    )
    missing_head = missing_head_indexes(store)
    read_events = 0
    recorded_read_events = 0
    try:
        events = read_artifact_read_events(project=store.project_key)
        read_events = len(events)
        recorded_read_events = sum(1 for event in events if event.recorded_link)
    except Exception:  # noqa: BLE001 - missing log is not a doctor failure
        read_events = 0
        recorded_read_events = 0
    try:
        outbox = inspect_artifact_link_outbox(store.project_key)
    except Exception:  # noqa: BLE001 - outbox diagnostics should not fail doctor
        outbox = None

    if fix:
        rebuild_existing_projections(store, rows)
        event_health = event_health_values(store)
        publication_health = publication_health_values(store)

    return ArtifactLinkHealthReport(
        skipped=False,
        dangling=tuple(dangling),
        unpublished_agent_refs=tuple(unpublished_agents),
        stale_tables=tuple(stale),
        missing_companions=tuple(missing),
        orphaned_companions=tuple(orphaned_companions),
        missing_head_indexes=tuple(missing_head),
        read_events=read_events,
        recorded_read_events=recorded_read_events,
        durable_read_rows=read_row_count(durable_rows),
        durable_store_rows=len(durable_rows),
        durable_sidecar_rows=len(sidecar_rows),
        aggregate_rows=len(aggregate_rows),
        expected_index_rows=len(expected_rows),
        aggregate_drift=drift,
        outbox_entries=0 if outbox is None else outbox.queued,
        outbox_event_entries=0 if outbox is None else outbox.event_queued,
        outbox_legacy_entries=0 if outbox is None else outbox.legacy_queued,
        outbox_invalid_entries=0 if outbox is None else outbox.invalid_queued,
        outbox_dropped=0 if outbox is None else outbox.dropped,
        outbox_oldest_age_seconds=(
            0.0 if outbox is None else outbox.oldest_age_seconds
        ),
        outbox_p95_age_seconds=0.0 if outbox is None else outbox.p95_age_seconds,
        event_objects=event_health.event_objects,
        event_pending=event_health.event_pending,
        event_pending_oldest_age_seconds=event_health.event_pending_oldest_age_seconds,
        event_pending_p95_age_seconds=event_health.event_pending_p95_age_seconds,
        event_validation_failures=event_health.event_validation_failures,
        event_reduction_errors=event_health.event_reduction_errors,
        event_orphaned_tombstones=event_health.event_orphaned_tombstones,
        publication_pending=publication_health.publication_pending,
        publication_aged=publication_health.publication_aged,
        publication_diagnostics=publication_health.publication_diagnostics,
        cutover_state=cutover_health.cutover_state,
        cutover_errors=cutover_health.cutover_errors,
        cutover_stragglers=cutover_health.cutover_stragglers,
        coverage=coverage_report(
            store,
            rows,
            context=resolution_context,
            index_rows=expected_rows,
            resolve_reference=resolve_cli_reference,
        ),
        rebuilt=fix,
        repaired_renames=repaired_renames,
    )


def dangling_and_orphaned_artifact_link_refs(
    store: ArtifactLinkStore,
) -> tuple[str, ...]:
    """Return the exact candidate refs ``sase artifact doctor --fix`` repairs.

    A housekeeping sweep that wants the rename-repair job without the rest of
    ``inspect_artifact_link_health``'s fix pass (which also rewrites Markdown
    ``## Links`` tables in place with no commit of its own) calls this and
    :func:`sase.sdd._artifact_link_renames.repair_historical_artifact_renames`
    directly instead.
    """

    rows = store_backed_rows(store.load_aggregate().get("rows", []))
    resolution_context = launch_artifact_ref_context(is_home_mode=False)
    dangling, _unpublished_agents = dangling_refs(
        rows,
        store,
        context=resolution_context,
        resolve_reference=resolve_cli_reference,
    )
    orphaned_companions = orphaned_link_indexes(store)
    return (*dangling, *orphaned_companions)


__all__ = [
    "ArtifactLinkHealthReport",
    "dangling_and_orphaned_artifact_link_refs",
    "inspect_artifact_link_health",
]

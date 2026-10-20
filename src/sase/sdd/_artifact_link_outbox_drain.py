"""Replay publishable artifact-link outbox entries into sidecar indexes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import time

from sase.sdd._artifact_link_authorize import (
    MachineSidecarWritability,
    probe_machine_writable_sidecar_root,
    sidecar_root_not_machine_writable_message,
)
from sase.sdd._artifact_link_outbox_io import (
    append_artifact_link_outbox_event as _append_artifact_link_outbox_event,
    inspect_artifact_link_outbox as _inspect_artifact_link_outbox,
    read_artifact_link_outbox_entries as _read_artifact_link_outbox_entries,
    rewrite_artifact_link_outbox_without_ids as _rewrite_without_ids,
)
from sase.sdd._artifact_link_outbox_types import (
    ArtifactLinkOutboxEntry as _ArtifactLinkOutboxEntry,
    sidecar_refs as _sidecar_refs,
)
from sase.sdd._artifact_link_store_support import BEAD_KIND, kind_of_ref
from sase.sdd.artifact_link_event_publisher import (
    artifact_link_alias_producer_id,
    artifact_link_derived_producer_id,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore, resolve_artifact_link_store

_TERMINAL_AGENT_STATES = frozenset({"completed", "failed", "stopped", "dismissed"})
_TERMINAL_AGENT_STATUSES = frozenset({"DONE", "FAILED", "STOPPED", "CANCELED"})
_SECONDS_PER_DAY = 24 * 60 * 60
_DEFAULT_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class _ParkedDrainDetail:
    """One operation moved onto the parked ledger this drain."""

    operation_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxDrainReport:
    """Result of one outbox drain attempt."""

    queued: int
    drained: int = 0
    retained: int = 0
    retained_legacy: int = 0
    retained_invalid: int = 0
    dropped: int = 0
    parked_new: int = 0
    parked_total: int = 0
    transient: int = 0
    bead_projection_failed: int = 0
    parked_details: tuple[_ParkedDrainDetail, ...] = ()
    committed: bool = False
    changed_indexes: tuple[Path, ...] = ()
    event_paths: tuple[Path, ...] = ()
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()
    deferred: bool = False


def drain_artifact_link_outbox(
    *,
    store: ArtifactLinkStore | None = None,
    agent_name: str | None = None,
    drop_stale_terminal: bool = True,
    push_after_commit: bool | str | None = "async",
    deadline: float | None = None,
    now: float | None = None,
) -> _ArtifactLinkOutboxDrainReport:
    """Replay publishable read-link rows into sidecar indexes.

    When *agent_name* is provided, only that agent's entries are considered for
    publication. Other entries remain queued.
    """

    from sase.sdd._artifact_link_event_project import (
        BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
    )
    from sase.sdd._artifact_link_outbox_parked import (
        append_artifact_link_parked_entries as _append_parked_entries,
        inspect_artifact_link_parked as _inspect_parked,
        parked_entry_from_outbox as _parked_entry_from_outbox,
    )

    link_store = store or resolve_artifact_link_store()
    observed_at = float(time.time() if now is None else now)
    _requeue_ready_parked_entries(link_store, now=observed_at)
    stats = _inspect_artifact_link_outbox(link_store.project_key)
    parked_total = _inspect_parked(link_store.project_key).parked
    entries = _read_artifact_link_outbox_entries(link_store.project_key)
    if not entries:
        return _ArtifactLinkOutboxDrainReport(
            queued=0,
            retained_legacy=stats.legacy_queued,
            retained_invalid=stats.invalid_queued,
            parked_total=parked_total,
        )
    if deadline is not None and time.monotonic() >= deadline:
        return _ArtifactLinkOutboxDrainReport(
            queued=len(entries),
            retained=len(entries),
            retained_legacy=stats.legacy_queued,
            retained_invalid=stats.invalid_queued,
            parked_total=parked_total,
            skip_diagnostics=(BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,),
            deferred=True,
        )

    selected, retained = _partition_selected(entries, agent_name=agent_name)
    terminal_cutoff = _terminal_cutoff() if drop_stale_terminal else None
    terminal_finished = (
        _terminal_agent_finished_times(selected) if terminal_cutoff is not None else {}
    )
    stale, candidates = _partition_stale_terminal(
        selected,
        terminal_cutoff=terminal_cutoff,
        terminal_finished=terminal_finished,
    )
    publishable, unpublished = _partition_publishable(candidates)
    retained.extend(unpublished)
    retained.extend(stale)
    writable_entries, unauthorized, skip_diagnostics = (
        _partition_machine_writable_entries(link_store, publishable)
    )
    retained.extend(unauthorized)

    event_drainable, event_only = _partition_event_drainable(writable_entries)
    retained.extend(event_only)
    event_report = publish_artifact_link_events(
        link_store,
        (entry.event for entry in event_drainable if entry.event is not None),
        push_after_commit=push_after_commit,  # type: ignore[arg-type]
        mutation_origin="machine",
        deadline=deadline,
    )
    published_event_ids = set(event_report.published_operation_ids)
    parked_by_id = {item.operation_id: item for item in event_report.parked_operations}
    parked_ids = set(parked_by_id)
    drainable_by_id = {entry.id: entry for entry in event_drainable}
    parked_records = [
        _parked_entry_from_outbox(
            drainable_by_id[operation_id],
            reasons=parked.reasons,
            endpoints=parked.endpoints,
            now=observed_at,
        )
        for operation_id, parked in parked_by_id.items()
        if operation_id in drainable_by_id
    ]
    parked_new = _append_parked_entries(link_store.project_key, parked_records)
    retained.extend(
        entry
        for entry in event_drainable
        if entry.id not in published_event_ids and entry.id not in parked_ids
    )
    event_skip_diagnostics = event_report.skip_diagnostics
    leave_ids = published_event_ids | parked_ids

    _rewrite_without_ids(
        link_store.project_key,
        drained_ids=leave_ids,
        dropped=stale,
    )
    parked_total = _inspect_parked(link_store.project_key).parked
    return _ArtifactLinkOutboxDrainReport(
        queued=len(entries),
        drained=len(published_event_ids),
        retained=(
            len(entries) - len(published_event_ids) - len(stale) - len(parked_ids)
        ),
        retained_legacy=stats.legacy_queued,
        retained_invalid=stats.invalid_queued,
        dropped=len(stale),
        parked_new=parked_new,
        parked_total=parked_total,
        transient=len(event_report.transient_operation_ids),
        bead_projection_failed=int(event_report.bead_projection_failed),
        parked_details=tuple(
            _ParkedDrainDetail(operation_id=item.operation_id, reasons=item.reasons)
            for item in event_report.parked_operations
        ),
        committed=event_report.committed,
        changed_indexes=(),
        event_paths=event_report.event_paths,
        publication_error=event_report.publication_error,
        skip_diagnostics=(*skip_diagnostics, *event_skip_diagnostics),
        deferred=event_report.deferred,
    )


def _partition_selected(
    entries: Iterable[_ArtifactLinkOutboxEntry], *, agent_name: str | None
) -> tuple[list[_ArtifactLinkOutboxEntry], list[_ArtifactLinkOutboxEntry]]:
    selected: list[_ArtifactLinkOutboxEntry] = []
    retained: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if agent_name is not None and entry.agent_name != agent_name:
            retained.append(entry)
        else:
            selected.append(entry)
    return selected, retained


def _partition_stale_terminal(
    entries: Iterable[_ArtifactLinkOutboxEntry],
    *,
    terminal_cutoff: float | None,
    terminal_finished: Mapping[str, float],
) -> tuple[list[_ArtifactLinkOutboxEntry], list[_ArtifactLinkOutboxEntry]]:
    stale: list[_ArtifactLinkOutboxEntry] = []
    active: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        finished_at = terminal_finished.get(entry.agent_name)
        if (
            terminal_cutoff is not None
            and finished_at is not None
            and finished_at <= terminal_cutoff
            and not _entry_is_eligible(entry)
        ):
            stale.append(entry)
        else:
            active.append(entry)
    return stale, active


def _partition_publishable(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[list[_ArtifactLinkOutboxEntry], list[_ArtifactLinkOutboxEntry]]:
    publishable: list[_ArtifactLinkOutboxEntry] = []
    retained: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if _entry_is_eligible(entry):
            publishable.append(entry)
        else:
            retained.append(entry)
    return publishable, retained


def _partition_machine_writable_entries(
    store: ArtifactLinkStore,
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[
    list[_ArtifactLinkOutboxEntry],
    list[_ArtifactLinkOutboxEntry],
    tuple[str, ...],
]:
    writable_entries: list[_ArtifactLinkOutboxEntry] = []
    unauthorized: list[_ArtifactLinkOutboxEntry] = []
    diagnostics: list[str] = []
    probes: dict[Path, MachineSidecarWritability] = {}
    for entry in entries:
        blocked = False
        for kind, root in _machine_writable_roots_for_entry(store, entry):
            resolved = root.expanduser().resolve(strict=False)
            probe = probes.get(resolved)
            if probe is None:
                probe = probe_machine_writable_sidecar_root(resolved)
                probes[resolved] = probe
                if not probe.writable:
                    diagnostics.append(
                        sidecar_root_not_machine_writable_message(
                            kind,
                            resolved,
                            diagnostic=probe.diagnostic or "not machine-writable",
                        )
                    )
            if not probe.writable:
                blocked = True
        if blocked:
            unauthorized.append(entry)
        else:
            writable_entries.append(entry)
    return writable_entries, unauthorized, tuple(dict.fromkeys(diagnostics))


def _machine_writable_roots_for_entry(
    store: ArtifactLinkStore,
    entry: _ArtifactLinkOutboxEntry,
) -> tuple[tuple[str, Path], ...]:
    roots: list[tuple[str, Path]] = []
    seen: set[tuple[str, Path]] = set()
    for ref in _sidecar_refs(entry):
        if not ref:
            continue
        kind = kind_of_ref(ref)
        root = store.beads_dir if kind == BEAD_KIND else store.sidecar_root_for(ref)
        if root is None:
            continue
        resolved = root.expanduser().resolve(strict=False)
        key = (kind, resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append((kind, root))
    return tuple(roots)


def _partition_event_drainable(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[list[_ArtifactLinkOutboxEntry], list[_ArtifactLinkOutboxEntry]]:
    drainable: list[_ArtifactLinkOutboxEntry] = []
    retained: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if entry.event is not None:
            drainable.append(entry)
        else:
            retained.append(entry)
    return drainable, retained


def _entry_is_eligible(entry: _ArtifactLinkOutboxEntry) -> bool:
    """Return whether *entry*'s own recording run earned release evidence.

    Eligibility is bound to the exact ``(run_id, agent_name)`` that recorded
    this entry -- an agent name or agent-session publication elsewhere is not
    sufficient, so a read-only neighbor's queued rows never ride along on a
    sibling run's real commit.
    """

    if _entry_is_trusted_machine_event(entry):
        return True

    from sase.sdd.artifact_link_release_evidence import (
        artifact_link_run_has_release_evidence,
    )

    try:
        return artifact_link_run_has_release_evidence(
            project_key=entry.project_key,
            run_id=entry.run_id,
            agent_id=entry.agent_name,
        )
    except Exception:  # noqa: BLE001 - unresolved evidence stays queued.
        return False


def _entry_is_trusted_machine_event(entry: _ArtifactLinkOutboxEntry) -> bool:
    event = entry.event
    if event is None:
        return False
    origin = str(event.get("origin") or "")
    if origin not in {"derived", "migrated"}:
        return False
    return entry.agent_name in {
        "sase",
        "machine",
        "artifact_link_backfill",
        artifact_link_derived_producer_id(),
        artifact_link_alias_producer_id(),
    }


def _terminal_cutoff() -> float | None:
    try:
        from sase.config import get_artifact_retention_max_age_days

        days = get_artifact_retention_max_age_days()
    except Exception:  # noqa: BLE001 - conservative default.
        days = _DEFAULT_RETENTION_DAYS
    if days <= 0:
        return None
    return time.time() - (days * _SECONDS_PER_DAY)


def _terminal_agent_finished_times(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> dict[str, float]:
    names = {entry.agent_name for entry in entries}
    if not names:
        return {}
    try:
        from sase.agents.catalog import build_agent_catalog_snapshot

        snapshot = build_agent_catalog_snapshot()
    except Exception:  # noqa: BLE001 - failing closed preserves the queue.
        return {}
    result: dict[str, float] = {}
    for row in snapshot.rows:
        if row.name not in names:
            continue
        state = (row.state or "").casefold()
        status = (row.status or "").upper()
        if (
            state not in _TERMINAL_AGENT_STATES
            and status not in _TERMINAL_AGENT_STATUSES
        ):
            continue
        if row.finished_at is not None:
            result[row.name] = float(row.finished_at)
    return result


def _requeue_ready_parked_entries(store: ArtifactLinkStore, *, now: float) -> None:
    """Move parked operations whose endpoints are now local back onto the queue."""

    from sase.sdd._artifact_link_outbox_parked import (
        PARKED_RECHECK_SECONDS,
        ArtifactLinkParkedEntry,
        read_artifact_link_parked_entries as _read_parked_entries,
        rewrite_artifact_link_parked_entries as _rewrite_parked_entries,
        touch_parked_checked_at as _touch_parked_checked_at,
    )

    parked = _read_parked_entries(store.project_key)
    if not parked:
        return
    kept: list[ArtifactLinkParkedEntry] = []
    requeued_ids: list[str] = []
    for item in parked:
        if now - item.last_checked_at < PARKED_RECHECK_SECONDS:
            kept.append(item)
            continue
        if item.entry.event is None or not _parked_endpoints_are_local(
            store, item.entry
        ):
            kept.append(_touch_parked_checked_at(item, now=now))
            continue
        _append_artifact_link_outbox_event(
            project_key=store.project_key,
            agent_name=item.entry.agent_name,
            run_id=item.entry.run_id,
            event=item.entry.event,
            now=now,
            check_parked=False,
        )
        requeued_ids.append(item.entry.id)
    if requeued_ids or len(kept) != len(parked):
        _rewrite_parked_entries(store.project_key, kept)


def _parked_endpoints_are_local(
    store: ArtifactLinkStore,
    entry: _ArtifactLinkOutboxEntry,
) -> bool:
    from sase.sdd._artifact_link_bead_endpoint import classify_bead_issue_ids
    from sase.sdd.artifact_link_beads import bead_id_from_ref

    issue_ids = tuple(
        issue_id for ref in _sidecar_refs(entry) if (issue_id := bead_id_from_ref(ref))
    )
    if not issue_ids:
        return False
    classified = classify_bead_issue_ids(issue_ids, store)
    return all(
        classified.get(issue_id) is not None and classified[issue_id].kind == "local"
        for issue_id in issue_ids
    )


__all__ = [
    "drain_artifact_link_outbox",
]

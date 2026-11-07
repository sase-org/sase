"""Replay publishable artifact-link outbox entries into sidecar indexes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import time

from sase.sdd._artifact_link_authorize import (
    MachineSidecarWritability,
    probe_machine_writable_sidecar_root,
    sidecar_root_not_machine_writable_message,
)
from sase.sdd._artifact_link_outbox_drain_support import (
    AgentTerminalTimes,
    DrainDeadlineExceeded as _DrainDeadline,
    check_drain_deadline as _check_deadline,
)
from sase.sdd._artifact_link_outbox_io import (
    append_artifact_link_outbox_event as _append_artifact_link_outbox_event,
    read_artifact_link_outbox_queue as _read_artifact_link_outbox_queue,
    rewrite_artifact_link_outbox_without_ids as _rewrite_without_ids,
)
from sase.sdd._artifact_link_outbox_types import (
    ArtifactLinkOutboxEntry as _ArtifactLinkOutboxEntry,
    event_key as _entry_event_key,
    sidecar_refs as _sidecar_refs,
)
from sase.sdd._artifact_link_store_support import BEAD_KIND, kind_of_ref
from sase.sdd.artifact_link_event_publisher import (
    artifact_link_alias_producer_id,
    artifact_link_derived_producer_id,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore, resolve_artifact_link_store

_SECONDS_PER_DAY = 24 * 60 * 60
_DEFAULT_RETENTION_DAYS = 90
# The agent catalog build can take tens of seconds; never start one with
# less than this much of the caller's deadline left.
_STALE_CATALOG_MIN_HEADROOM_SECONDS = 60.0
_STALE_DROP_DEFERRED_DIAGNOSTIC = "deferred stale terminal drop: insufficient budget"


@dataclass(frozen=True, slots=True)
class _ParkedDrainDetail:
    """One operation moved onto the parked ledger this drain."""

    operation_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxDrainReport:
    """Result of one outbox drain attempt."""

    queued: int
    selected_queued: int = 0
    selected_retained: int = 0
    drained: int = 0
    quarantined: int = 0
    retained: int = 0
    retained_legacy: int = 0
    retained_invalid: int = 0
    dropped: int = 0
    parked_new: int = 0
    parked_total: int = 0
    transient: int = 0
    bead_projection_failed: int = 0
    parked_details: tuple[_ParkedDrainDetail, ...] = ()
    quarantine_details: tuple[str, ...] = ()
    committed: bool = False
    changed_indexes: tuple[Path, ...] = ()
    event_paths: tuple[Path, ...] = ()
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()
    deferred: bool = False
    stale_checked: bool = False
    phase_seconds: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class _StaleTerminalDecision:
    """Outcome of one stale-terminal evaluation over ineligible entries."""

    stale: tuple[_ArtifactLinkOutboxEntry, ...] = ()
    checked: bool = False
    diagnostics: tuple[str, ...] = ()


def drain_artifact_link_outbox(
    *,
    store: ArtifactLinkStore | None = None,
    agent_name: str | None = None,
    agent_names: Iterable[str] | None = None,
    drop_stale_terminal: bool = True,
    push_after_commit: bool | str | None = "async",
    deadline: float | None = None,
    now: float | None = None,
    terminal_times: AgentTerminalTimes | None = None,
) -> _ArtifactLinkOutboxDrainReport:
    """Replay publishable read-link rows into sidecar indexes.

    When *agent_name* or *agent_names* is provided, only those agents' entries
    are considered for publication. Other entries remain queued. Supplying
    both selectors is an error.

    The outbox is parsed once and release evidence is loaded once, so a drain
    costs O(rows + evidence lines). *terminal_times* lets several drains
    share one lazily built agent catalog; ``None`` builds a private one only
    if some ineligible row is old enough to be dropped.
    """

    from sase.sdd._artifact_link_event_project import (
        BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
    )
    from sase.sdd._artifact_link_outbox_parked import (
        append_artifact_link_parked_entries as _append_parked_entries,
        inspect_artifact_link_parked as _inspect_parked,
        parked_entry_from_outbox as _parked_entry_from_outbox,
    )

    if agent_name is not None and agent_names is not None:
        raise ValueError("specify either agent_name or agent_names, not both")
    selected_names = frozenset(agent_names) if agent_names is not None else None
    link_store = store or resolve_artifact_link_store()
    observed_at = float(time.time() if now is None else now)
    phases: dict[str, float] = {}
    _requeue_ready_parked_entries(link_store, now=observed_at)
    phase_started = time.monotonic()
    queue = _read_artifact_link_outbox_queue(link_store.project_key)
    phases["read"] = time.monotonic() - phase_started
    parked_total = _inspect_parked(link_store.project_key).parked
    entries = queue.entries
    if not entries:
        return _ArtifactLinkOutboxDrainReport(
            queued=0,
            selected_queued=0,
            selected_retained=0,
            retained_legacy=queue.legacy_queued,
            retained_invalid=queue.invalid_queued,
            parked_total=parked_total,
            stale_checked=drop_stale_terminal,
            phase_seconds=tuple(phases.items()),
        )
    selected, _unselected = _partition_selected(
        entries,
        agent_name=agent_name,
        agent_names=selected_names,
    )

    def _deferred_report() -> _ArtifactLinkOutboxDrainReport:
        return _ArtifactLinkOutboxDrainReport(
            queued=len(entries),
            retained=len(entries),
            selected_queued=len(selected),
            selected_retained=len(selected),
            retained_legacy=queue.legacy_queued,
            retained_invalid=queue.invalid_queued,
            parked_total=parked_total,
            skip_diagnostics=(BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,),
            deferred=True,
            phase_seconds=tuple(phases.items()),
        )

    if deadline is not None and time.monotonic() >= deadline:
        return _deferred_report()

    try:
        phase_started = time.monotonic()
        evidence_index = _load_evidence_index(link_store.project_key, selected)
        phases["evidence"] = time.monotonic() - phase_started

        phase_started = time.monotonic()
        eligible: list[_ArtifactLinkOutboxEntry] = []
        ineligible: list[_ArtifactLinkOutboxEntry] = []
        for index, entry in enumerate(selected):
            _check_deadline(deadline, index)
            if _entry_is_eligible(entry, evidence_index):
                eligible.append(entry)
            else:
                ineligible.append(entry)
        phases["eligibility"] = time.monotonic() - phase_started

        stale_decision = _StaleTerminalDecision()
        if drop_stale_terminal:
            stale_decision = _stale_terminal_entries(
                ineligible,
                now=observed_at,
                deadline=deadline,
                terminal_times=(
                    terminal_times
                    if terminal_times is not None
                    else AgentTerminalTimes()
                ),
                phases=phases,
            )
        _check_deadline(deadline, 0)
    except _DrainDeadline:
        return _deferred_report()
    stale = list(stale_decision.stale)

    phase_started = time.monotonic()
    writable_entries, _unauthorized, skip_diagnostics = (
        _partition_machine_writable_entries(link_store, eligible)
    )
    event_drainable, _event_only = _partition_event_drainable(writable_entries)
    event_report = publish_artifact_link_events(
        link_store,
        (entry.event for entry in event_drainable if entry.event is not None),
        push_after_commit=push_after_commit,  # type: ignore[arg-type]
        mutation_origin="machine",
        deadline=deadline,
    )
    published_event_keys = set(event_report.published_event_keys)
    parked_by_key = {
        (item.operation_id, item.digest): item
        for item in event_report.parked_operations
    }
    parked_event_keys = set(parked_by_key)
    quarantined_event_keys = set(event_report.quarantined_event_keys)
    drainable_by_key = {
        key: entry
        for entry in event_drainable
        if (key := _entry_event_key(entry)) is not None
    }
    parked_records = [
        _parked_entry_from_outbox(
            drainable_by_key[event_key],
            reasons=parked.reasons,
            endpoints=parked.endpoints,
            now=observed_at,
        )
        for event_key, parked in parked_by_key.items()
        if event_key in drainable_by_key
    ]
    parked_new = _append_parked_entries(link_store.project_key, parked_records)
    phases["publish"] = time.monotonic() - phase_started
    event_skip_diagnostics = event_report.skip_diagnostics
    settled_event_keys = (
        published_event_keys | parked_event_keys | quarantined_event_keys
    )
    drained_count = sum(
        1
        for entry in event_drainable
        if _entry_event_key(entry) in published_event_keys
    )
    parked_count = sum(
        1 for entry in event_drainable if _entry_event_key(entry) in parked_event_keys
    )
    quarantined_count = sum(
        1
        for entry in event_drainable
        if _entry_event_key(entry) in quarantined_event_keys
    )

    if settled_event_keys or stale or queue.has_duplicate_ids:
        phase_started = time.monotonic()
        _rewrite_without_ids(
            link_store.project_key,
            settled_event_keys=settled_event_keys,
            dropped=stale,
        )
        phases["rewrite"] = time.monotonic() - phase_started
    parked_total = _inspect_parked(link_store.project_key).parked
    return _ArtifactLinkOutboxDrainReport(
        queued=len(entries),
        selected_queued=len(selected),
        selected_retained=max(
            0,
            len(selected)
            - drained_count
            - len(stale)
            - parked_count
            - quarantined_count,
        ),
        drained=drained_count,
        quarantined=quarantined_count,
        retained=(
            len(entries) - drained_count - len(stale) - parked_count - quarantined_count
        ),
        retained_legacy=queue.legacy_queued,
        retained_invalid=queue.invalid_queued,
        dropped=len(stale),
        parked_new=parked_new,
        parked_total=parked_total,
        transient=len(event_report.transient_operation_ids),
        bead_projection_failed=int(event_report.bead_projection_failed),
        parked_details=tuple(
            _ParkedDrainDetail(operation_id=item.operation_id, reasons=item.reasons)
            for item in event_report.parked_operations
        ),
        quarantine_details=tuple(
            str(finding.render())
            for finding in event_report.quarantine_findings
            if hasattr(finding, "render")
        ),
        committed=event_report.committed,
        changed_indexes=(),
        event_paths=event_report.event_paths,
        publication_error=event_report.publication_error,
        skip_diagnostics=(
            *stale_decision.diagnostics,
            *skip_diagnostics,
            *event_skip_diagnostics,
        ),
        deferred=event_report.deferred,
        stale_checked=stale_decision.checked,
        phase_seconds=tuple(phases.items()),
    )


def _partition_selected(
    entries: Iterable[_ArtifactLinkOutboxEntry],
    *,
    agent_name: str | None,
    agent_names: frozenset[str] | None,
) -> tuple[list[_ArtifactLinkOutboxEntry], list[_ArtifactLinkOutboxEntry]]:
    selected: list[_ArtifactLinkOutboxEntry] = []
    retained: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if (agent_name is not None and entry.agent_name != agent_name) or (
            agent_names is not None and entry.agent_name not in agent_names
        ):
            retained.append(entry)
        else:
            selected.append(entry)
    return selected, retained


def _load_evidence_index(
    project_key: str,
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> frozenset[tuple[str, str]]:
    """Load release evidence once, only if some entry actually needs it."""

    if all(_entry_is_trusted_machine_event(entry) for entry in entries):
        return frozenset()
    from sase.sdd.artifact_link_release_evidence import (
        load_artifact_link_release_evidence_index,
    )

    try:
        return load_artifact_link_release_evidence_index(project_key)
    except Exception:  # noqa: BLE001 - unresolved evidence keeps rows queued.
        return frozenset()


def _stale_terminal_entries(
    ineligible: Iterable[_ArtifactLinkOutboxEntry],
    *,
    now: float,
    deadline: float | None,
    terminal_times: AgentTerminalTimes,
    phases: dict[str, float],
) -> _StaleTerminalDecision:
    """Pick never-publishable rows whose terminal agent aged past retention.

    An agent finishes after it records its rows, so a row created after the
    cutoff can never be stale; only older rows need the agent catalog, and
    with none of them the catalog is never consulted at all.
    """

    cutoff = _terminal_cutoff(now)
    if cutoff is None:
        return _StaleTerminalDecision(checked=True)
    candidates = [entry for entry in ineligible if entry.created_at <= cutoff]
    if not candidates:
        return _StaleTerminalDecision(checked=True)
    if (
        not terminal_times.built
        and deadline is not None
        and deadline - time.monotonic() < _STALE_CATALOG_MIN_HEADROOM_SECONDS
    ):
        return _StaleTerminalDecision(diagnostics=(_STALE_DROP_DEFERRED_DIAGNOSTIC,))
    phase_started = time.monotonic()
    finished = terminal_times.finished_times(entry.agent_name for entry in candidates)
    phases["catalog"] = time.monotonic() - phase_started
    stale = tuple(
        entry
        for entry in candidates
        if (finished_at := finished.get(entry.agent_name)) is not None
        and finished_at <= cutoff
    )
    return _StaleTerminalDecision(stale=stale, checked=terminal_times.ok)


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


def _entry_is_eligible(
    entry: _ArtifactLinkOutboxEntry,
    evidence_index: frozenset[tuple[str, str]],
) -> bool:
    """Return whether *entry*'s own recording run earned release evidence.

    Eligibility is bound to the exact ``(run_id, agent_name)`` that recorded
    this entry -- an agent name or agent-session publication elsewhere is not
    sufficient, so a read-only neighbor's queued rows never ride along on a
    sibling run's real commit. *evidence_index* is the drain's one-shot load
    of validated release-evidence pairs.
    """

    if _entry_is_trusted_machine_event(entry):
        return True
    if not entry.run_id or not entry.agent_name:
        return False
    return (entry.run_id, entry.agent_name) in evidence_index


def _entry_is_trusted_machine_event(entry: _ArtifactLinkOutboxEntry) -> bool:
    event = entry.event
    if event is None:
        return False
    origin = str(event.get("origin") or "")
    if origin not in {"derived", "migrated", "prompt_ref", "prompt_prose"}:
        return False
    return entry.agent_name in {
        "sase",
        "machine",
        "artifact_link_backfill",
        artifact_link_derived_producer_id(),
        artifact_link_alias_producer_id(),
    }


def _terminal_cutoff(now: float) -> float | None:
    try:
        from sase.config import get_artifact_retention_max_age_days

        days = get_artifact_retention_max_age_days()
    except Exception:  # noqa: BLE001 - conservative default.
        days = _DEFAULT_RETENTION_DAYS
    if days <= 0:
        return None
    return now - (days * _SECONDS_PER_DAY)


def _requeue_ready_parked_entries(store: ArtifactLinkStore, *, now: float) -> None:
    """Move parked operations whose endpoints are now local back onto the queue.

    Every recheck persists its ``last_checked_at`` so the 24h throttle holds
    across drains; the ledger update re-reads under its lock so an entry
    parked concurrently by another drain is never lost.
    """

    from sase.sdd._artifact_link_outbox_parked import (
        PARKED_RECHECK_SECONDS,
        read_artifact_link_parked_entries as _read_parked_entries,
        update_artifact_link_parked_entries as _update_parked_entries,
    )

    parked = _read_parked_entries(store.project_key)
    if not parked:
        return
    touched: dict[str, float] = {}
    requeued_ids: list[str] = []
    for item in parked:
        if now - item.last_checked_at < PARKED_RECHECK_SECONDS:
            continue
        if item.entry.event is None or not _parked_endpoints_are_local(
            store, item.entry
        ):
            touched[item.entry.id] = now
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
    if touched or requeued_ids:
        _update_parked_entries(
            store.project_key,
            touched=touched,
            removed=requeued_ids,
        )


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

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
    read_artifact_link_outbox_entries as _read_artifact_link_outbox_entries,
    rewrite_artifact_link_outbox_without_ids as _rewrite_without_ids,
)
from sase.sdd._artifact_link_outbox_types import (
    ArtifactLinkOutboxEntry as _ArtifactLinkOutboxEntry,
    sidecar_refs as _sidecar_refs,
)
from sase.sdd._artifact_link_store_support import kind_of_ref
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from sase.sdd.artifact_link_store import ArtifactLinkStore, resolve_artifact_link_store

_TERMINAL_AGENT_STATES = frozenset({"completed", "failed", "stopped", "dismissed"})
_TERMINAL_AGENT_STATUSES = frozenset({"DONE", "FAILED", "STOPPED", "CANCELED"})
_SECONDS_PER_DAY = 24 * 60 * 60
_DEFAULT_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxDrainReport:
    """Result of one outbox drain attempt."""

    queued: int
    drained: int = 0
    retained: int = 0
    dropped: int = 0
    committed: bool = False
    changed_indexes: tuple[Path, ...] = ()
    event_paths: tuple[Path, ...] = ()
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()


def drain_artifact_link_outbox(
    *,
    store: ArtifactLinkStore | None = None,
    agent_name: str | None = None,
    drop_stale_terminal: bool = True,
    push_after_commit: bool | str | None = "async",
) -> _ArtifactLinkOutboxDrainReport:
    """Replay publishable read-link rows into sidecar indexes.

    When *agent_name* is provided, only that agent's entries are considered for
    publication. Other entries remain queued.
    """

    link_store = store or resolve_artifact_link_store()
    entries = _read_artifact_link_outbox_entries(link_store.project_key)
    if not entries:
        return _ArtifactLinkOutboxDrainReport(queued=0)

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
    )
    published_event_ids = set(event_report.published_operation_ids)
    retained.extend(
        entry for entry in event_drainable if entry.id not in published_event_ids
    )
    event_skip_diagnostics = event_report.skip_diagnostics

    _rewrite_without_ids(
        link_store.project_key,
        drained_ids=published_event_ids,
        dropped=stale,
    )
    return _ArtifactLinkOutboxDrainReport(
        queued=len(entries),
        drained=len(published_event_ids),
        retained=(len(entries) - len(published_event_ids) - len(stale)),
        dropped=len(stale),
        committed=event_report.committed,
        changed_indexes=(),
        event_paths=event_report.event_paths,
        publication_error=event_report.publication_error,
        skip_diagnostics=(*skip_diagnostics, *event_skip_diagnostics),
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
        for ref in _sidecar_refs(entry):
            root = store.sidecar_root_for(ref)
            if root is None:
                continue
            resolved = root.expanduser().resolve(strict=False)
            probe = probes.get(resolved)
            if probe is None:
                probe = probe_machine_writable_sidecar_root(resolved)
                probes[resolved] = probe
                if not probe.writable:
                    diagnostics.append(
                        sidecar_root_not_machine_writable_message(
                            kind_of_ref(ref),
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
    this entry -- an agent name or family publication elsewhere is not
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
    return entry.agent_name in {"sase", "machine", "artifact_link_backfill"}


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


__all__ = [
    "drain_artifact_link_outbox",
]

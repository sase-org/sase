"""Machine-local operation journal for artifact-link mutations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from sase.core.paths import sase_projects_dir, validate_sase_project_name
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_authorize import (
    MachineSidecarWritability,
    probe_machine_writable_sidecar_root,
    sidecar_root_not_machine_writable_message,
)
from sase.sdd._artifact_link_store_support import (
    kind_of_ref,
    sidecar_index_path,
    validate_artifact_link_row,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore, resolve_artifact_link_store

ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION = 2
ARTIFACT_LINK_OUTBOX_FILENAME = "artifact-link-outbox.jsonl"
ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME = "artifact-link-outbox-dropped.jsonl"

_TERMINAL_AGENT_STATES = frozenset({"completed", "failed", "stopped", "dismissed"})
_TERMINAL_AGENT_STATUSES = frozenset({"DONE", "FAILED", "STOPPED", "CANCELED"})
_SECONDS_PER_DAY = 24 * 60 * 60
_DEFAULT_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxEntry:
    """One queued artifact-link operation plus its recording run's identity.

    ``run_id`` binds this entry to the specific run that recorded it (see
    ``sase.sdd.artifact_link_release_evidence``): a different run of the same
    agent, or another agent in the same family, must not be able to release
    it merely by publishing something of its own.

    New schema-v2 entries store the canonical event payload. ``row`` is the
    legacy projection used while old readers still consume ``links/*.json``.
    Row-only entries are preserved for compatibility with queues written before
    the operation journal existed.
    """

    schema_version: int
    id: str
    created_at: float
    project_key: str
    agent_name: str
    run_id: str
    row: dict[str, Any] | None = None
    event: dict[str, Any] | None = None

    @property
    def logical_key(self) -> tuple[str, str, str]:
        if self.row is None:
            raise RuntimeError("artifact-link outbox entry has no legacy row")
        return _row_key(self.row)

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "created_at": self.created_at,
            "project_key": self.project_key,
            "agent_name": self.agent_name,
            "run_id": self.run_id,
        }
        if self.event is not None:
            payload["event"] = dict(self.event)
        else:
            payload["row"] = dict(self.row or {})
        return payload


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxStats:
    """Current queue depth plus cumulative drops."""

    queued: int
    dropped: int


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxDrainReport:
    """Result of one outbox drain attempt."""

    queued: int
    drained: int = 0
    retained: int = 0
    dropped: int = 0
    committed: bool = False
    changed_indexes: tuple[Path, ...] = ()
    skip_diagnostics: tuple[str, ...] = ()


def _artifact_link_outbox_path(project_key: str) -> Path:
    """Return ``~/.sase/projects/<key>/artifact-link-outbox.jsonl``."""

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / ARTIFACT_LINK_OUTBOX_FILENAME


def _artifact_link_outbox_dropped_path(project_key: str) -> Path:
    """Return the project-local dropped-entry audit JSONL path."""

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME


def append_artifact_link_outbox_entry(
    *,
    project_key: str,
    agent_name: str,
    run_id: str,
    row: Mapping[str, Any],
    now: float | None = None,
    entry_id: str | None = None,
) -> _ArtifactLinkOutboxEntry:
    """Append one replayable artifact-link event to the project outbox.

    *run_id* identifies the specific run that recorded this row (typically
    ``SASE_AGENT_TIMESTAMP``). A blank value is accepted -- it simply means
    this entry can never earn release evidence and stays local until it is
    pruned by the existing retention policy.
    """

    operation_id = _operation_id(entry_id or uuid4().hex)
    event = _event_from_row(
        row,
        project_key=project_key,
        operation_id=operation_id,
    )
    [legacy_row] = _rows_from_events((event,))
    entry = _ArtifactLinkOutboxEntry(
        schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
        id=operation_id,
        created_at=float(time.time() if now is None else now),
        project_key=project_key,
        agent_name=_required_text(agent_name, "agent_name"),
        run_id=str(run_id or ""),
        row=legacy_row,
        event=event,
    )
    path = _artifact_link_outbox_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(entry.to_json_dict(), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()
    return entry


def append_artifact_link_outbox_event(
    *,
    project_key: str,
    agent_name: str,
    run_id: str,
    event: Mapping[str, Any],
    now: float | None = None,
) -> _ArtifactLinkOutboxEntry:
    """Append one canonical event payload to the project outbox."""

    canonical = _canonicalize_event(event)
    operation_id = _event_operation_id(canonical)
    event_project = _required_text(canonical.get("project_key"), "project_key")
    if event_project != project_key:
        raise ValueError("artifact-link outbox event project mismatch")
    rows = _rows_from_events((canonical,))
    entry = _ArtifactLinkOutboxEntry(
        schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
        id=operation_id,
        created_at=float(time.time() if now is None else now),
        project_key=project_key,
        agent_name=_required_text(agent_name, "agent_name"),
        run_id=str(run_id or ""),
        row=rows[0] if len(rows) == 1 else None,
        event=canonical,
    )
    path = _artifact_link_outbox_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(entry.to_json_dict(), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()
    return entry


def _read_artifact_link_outbox_entries(
    project_key: str,
) -> tuple[_ArtifactLinkOutboxEntry, ...]:
    """Read valid queued outbox entries, skipping malformed JSONL rows."""

    path = _artifact_link_outbox_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.is_file():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()
    entries: list[_ArtifactLinkOutboxEntry] = []
    for line in lines:
        if not line.strip():
            continue
        entry = _entry_from_line(line, project_key)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def pending_artifact_link_outbox_events(
    project_key: str,
) -> tuple[dict[str, Any], ...]:
    """Return queued schema-v2 events for local pending-link overlays."""

    return tuple(
        dict(entry.event)
        for entry in _read_artifact_link_outbox_entries(project_key)
        if entry.event is not None
    )


def inspect_artifact_link_outbox(project_key: str) -> _ArtifactLinkOutboxStats:
    """Return doctor-facing outbox queue and drop counts."""

    return _ArtifactLinkOutboxStats(
        queued=len(_read_artifact_link_outbox_entries(project_key)),
        dropped=_count_jsonl_rows(_artifact_link_outbox_dropped_path(project_key)),
    )


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

    legacy_drainable, event_only = _partition_legacy_drainable(writable_entries)
    retained.extend(event_only)

    changed_indexes = _upsert_publishable_entries(link_store, legacy_drainable)
    if changed_indexes:
        committed = _commit_outbox_indexes(
            link_store,
            changed_indexes,
            push_after_commit=push_after_commit,
        )
        if not committed:
            return _ArtifactLinkOutboxDrainReport(
                queued=len(entries),
                retained=len(entries),
                changed_indexes=tuple(changed_indexes),
                skip_diagnostics=skip_diagnostics,
            )
    else:
        committed = False

    _rewrite_without_ids(
        link_store.project_key,
        drained_ids={entry.id for entry in legacy_drainable},
        dropped=stale,
    )
    return _ArtifactLinkOutboxDrainReport(
        queued=len(entries),
        drained=len(legacy_drainable),
        retained=len(entries) - len(legacy_drainable) - len(stale),
        dropped=len(stale),
        committed=committed,
        changed_indexes=tuple(changed_indexes),
        skip_diagnostics=skip_diagnostics,
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


def _partition_legacy_drainable(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[list[_ArtifactLinkOutboxEntry], list[_ArtifactLinkOutboxEntry]]:
    drainable: list[_ArtifactLinkOutboxEntry] = []
    retained: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if _entry_can_drain_to_legacy_index(entry):
            drainable.append(entry)
        else:
            retained.append(entry)
    return drainable, retained


def _entry_can_drain_to_legacy_index(entry: _ArtifactLinkOutboxEntry) -> bool:
    """Return whether today's legacy index drain can safely publish *entry*."""

    if entry.event is None:
        return entry.row is not None
    kind = entry.event.get("kind")
    if not isinstance(kind, dict):
        return False
    return str(kind.get("type") or "") in {
        "observation",
        "edge-put",
        "baseline-import",
    }


def _upsert_publishable_entries(
    store: ArtifactLinkStore,
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> list[Path]:
    changed_indexes: list[Path] = []
    for row in _converged_rows(entries):
        existing_uses = _existing_uses(store, row)
        desired_uses = _row_uses(row)
        if str(row.get("origin") or "") == "read":
            # A queued read row only ever knows this batch's own increment
            # (see `_converged_rows`), never the durable total, so the
            # target is what's already on disk plus that increment.
            desired_uses += existing_uses
        if existing_uses >= desired_uses:
            changed_indexes.extend(_existing_index_paths(store, row))
            continue
        delta = dict(row)
        delta["uses"] = desired_uses - existing_uses
        outcome = store.upsert_row(delta)
        changed_indexes.extend(outcome.get("changed_indexes") or ())
    return list(dict.fromkeys(changed_indexes))


def _converged_rows(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[dict[str, Any], ...]:
    """Return legacy rows that preserve queued operation identity.

    Schema-v2 event entries reduce through the Rust event reducer, so distinct
    operation ids remain distinct observations and exact duplicate delivery is
    idempotent. Row-only entries keep the legacy convergence rules for queues
    written before the operation journal.
    """

    event_entries: list[_ArtifactLinkOutboxEntry] = []
    legacy_entries: list[_ArtifactLinkOutboxEntry] = []
    for entry in entries:
        if entry.event is not None:
            event_entries.append(entry)
        else:
            legacy_entries.append(entry)

    rows: list[dict[str, Any]] = []
    rows.extend(_rows_from_events(entry.event for entry in event_entries))
    rows.extend(_converged_legacy_rows(legacy_entries))
    return tuple(rows)


def _converged_legacy_rows(
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[dict[str, Any], ...]:
    """Combine row-only legacy entries sharing one logical edge."""

    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for entry in entries:
        if entry.row is None:
            continue
        key = entry.logical_key
        if key not in by_key:
            order.append(key)
            by_key[key] = dict(entry.row)
            continue
        current = by_key[key]
        if str(entry.row.get("origin") or "") == "read":
            merged = dict(entry.row)
            merged["uses"] = _row_uses(current) + _row_uses(entry.row)
            by_key[key] = merged
        elif _row_uses(entry.row) >= _row_uses(current):
            by_key[key] = dict(entry.row)
    return tuple(validate_artifact_link_row(by_key[key]) for key in order)


def _existing_uses(store: ArtifactLinkStore, row: Mapping[str, Any]) -> int:
    source, relation, target = _row_key(row)
    candidates = [
        *store.load_artifact_rows(source),
        *store.load_artifact_rows(target),
    ]
    return max(
        (
            _row_uses(candidate)
            for candidate in candidates
            if _row_key(candidate) == (source, relation, target)
        ),
        default=0,
    )


def _existing_index_paths(
    store: ArtifactLinkStore, row: Mapping[str, Any]
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for ref in (str(row.get("source_ref") or ""), str(row.get("target_ref") or "")):
        root = store.sidecar_root_for(ref)
        if root is None:
            continue
        path = sidecar_index_path(root, ref)
        if path.is_file():
            paths.append(path)
    return tuple(dict.fromkeys(paths))


def _commit_outbox_indexes(
    store: ArtifactLinkStore,
    changed_indexes: list[Path],
    *,
    push_after_commit: bool | str | None,
) -> bool:
    from sase.sdd._artifact_link_commit import commit_artifact_link_indexes

    result = commit_artifact_link_indexes(
        changed_indexes,
        store=store.sdd_store,
        repo_roots=tuple(store.sidecar_roots.values()),
        push_after_commit=push_after_commit,  # type: ignore[arg-type]
        mutation_origin="machine",
    )
    return bool(result)


def _rewrite_without_ids(
    project_key: str,
    *,
    drained_ids: set[str],
    dropped: list[_ArtifactLinkOutboxEntry],
) -> None:
    path = _artifact_link_outbox_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        current = _read_entries_unlocked(path, project_key)
        dropped_ids = {dropped_entry.id for dropped_entry in dropped}
        kept = [
            entry
            for entry in current
            if entry.id not in drained_ids and entry.id not in dropped_ids
        ]
        _write_jsonl(path, [entry.to_json_dict() for entry in kept])
    if dropped:
        _append_dropped(project_key, dropped)


def _append_dropped(
    project_key: str, entries: Iterable[_ArtifactLinkOutboxEntry]
) -> None:
    path = _artifact_link_outbox_dropped_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            for entry in entries:
                payload = entry.to_json_dict()
                payload["dropped_at"] = time.time()
                payload["drop_reason"] = "terminal_unpublished_retention_expired"
                json.dump(payload, output_file, sort_keys=True)
                output_file.write("\n")
            output_file.flush()


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as output_file:
            for row in rows:
                json.dump(dict(row), output_file, sort_keys=True)
                output_file.write("\n")
            output_file.flush()
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _entry_from_line(line: str, project_key: str) -> _ArtifactLinkOutboxEntry | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _entry_from_mapping(data, project_key)
    except (TypeError, ValueError, RuntimeError):
        return None


def _read_entries_unlocked(
    path: Path, project_key: str
) -> tuple[_ArtifactLinkOutboxEntry, ...]:
    if not path.is_file():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    entries: list[_ArtifactLinkOutboxEntry] = []
    for line in lines:
        if not line.strip():
            continue
        entry = _entry_from_line(line, project_key)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def _entry_from_mapping(
    data: Mapping[str, Any],
    project_key: str,
) -> _ArtifactLinkOutboxEntry:
    schema_version = _integer_schema_version(data.get("schema_version"))
    entry_project = _required_text(data.get("project_key"), "project_key")
    if entry_project != project_key:
        raise RuntimeError("artifact-link outbox project mismatch")
    created_at = data.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        raise RuntimeError("artifact-link outbox created_at must be a number")
    raw_event = data.get("event")
    if isinstance(raw_event, dict):
        if schema_version != ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION:
            raise RuntimeError("unsupported artifact-link event outbox schema")
        event = _canonicalize_event(raw_event)
        operation_id = _event_operation_id(event)
        if _required_text(data.get("id"), "id") != operation_id:
            raise RuntimeError("artifact-link outbox id must match operation_id")
        event_project = _required_text(event.get("project_key"), "project_key")
        if event_project != project_key:
            raise RuntimeError("artifact-link outbox event project mismatch")
        rows = _rows_from_events((event,))
        return _ArtifactLinkOutboxEntry(
            schema_version=schema_version,
            id=operation_id,
            created_at=float(created_at),
            project_key=entry_project,
            agent_name=_required_text(data.get("agent_name"), "agent_name"),
            run_id=str(data.get("run_id") or ""),
            row=rows[0] if len(rows) == 1 else None,
            event=event,
        )

    if schema_version not in {1, ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION}:
        raise RuntimeError("unsupported artifact-link outbox schema")
    row = data.get("row")
    if not isinstance(row, dict):
        raise RuntimeError("artifact-link outbox row must be an object")
    return _ArtifactLinkOutboxEntry(
        schema_version=schema_version,
        id=_required_text(data.get("id"), "id"),
        created_at=float(created_at),
        project_key=entry_project,
        agent_name=_required_text(data.get("agent_name"), "agent_name"),
        run_id=str(data.get("run_id") or ""),
        row=validate_artifact_link_row(row),
    )


def _count_jsonl_rows(path: Path) -> int:
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.is_file():
            return 0
        try:
            return sum(
                1 for line in path.read_text(encoding="utf-8").splitlines() if line
            )
        except OSError:
            return 0


def _entry_is_eligible(entry: _ArtifactLinkOutboxEntry) -> bool:
    """Return whether *entry*'s own recording run earned release evidence.

    Eligibility is bound to the exact ``(run_id, agent_name)`` that recorded
    this entry -- an agent name or family publication elsewhere is not
    sufficient, so a read-only neighbor's queued rows never ride along on a
    sibling run's real commit.
    """

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


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_ref") or ""),
        str(row.get("relation") or ""),
        str(row.get("target_ref") or ""),
    )


def _sidecar_refs(entry: _ArtifactLinkOutboxEntry) -> tuple[str, ...]:
    if entry.row is not None:
        return (
            str(entry.row.get("source_ref") or ""),
            str(entry.row.get("target_ref") or ""),
        )
    event = entry.event
    if event is None:
        return ()
    kind = event.get("kind")
    if not isinstance(kind, dict):
        return ()
    event_type = str(kind.get("type") or "")
    if event_type in {"observation", "edge-put", "edge-remove"}:
        edge = kind.get("edge")
        if not isinstance(edge, dict):
            return ()
        edge_kind = str(edge.get("kind") or "")
        if edge_kind == "directed":
            return (
                str(edge.get("source_ref") or ""),
                str(edge.get("target_ref") or ""),
            )
        if edge_kind == "undirected":
            return (
                str(edge.get("left_ref") or ""),
                str(edge.get("right_ref") or ""),
            )
    if event_type == "alias":
        return (
            str(kind.get("old_ref") or ""),
            str(kind.get("new_ref") or ""),
        )
    if event_type == "baseline-import":
        refs: list[str] = []
        rows = kind.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                refs.append(str(row.get("source_ref") or ""))
                refs.append(str(row.get("target_ref") or ""))
        return tuple(refs)
    return ()


def _row_uses(row: Mapping[str, Any]) -> int:
    try:
        uses = int(row.get("uses") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, uses)


def _event_from_row(
    row: Mapping[str, Any],
    *,
    project_key: str,
    operation_id: str,
) -> dict[str, Any]:
    canonical_row = validate_artifact_link_row(row)
    origin = str(canonical_row.get("origin") or "")
    edge = {
        "kind": "directed",
        "source_ref": str(canonical_row.get("source_ref") or ""),
        "relation": str(canonical_row.get("relation") or ""),
        "target_ref": str(canonical_row.get("target_ref") or ""),
    }
    if origin in {"read", "prompt_ref"}:
        kind = {
            "type": "observation",
            "edge": edge,
            "description": str(canonical_row.get("description") or ""),
            "occurrences": _row_uses(canonical_row),
        }
    else:
        kind = {
            "type": "edge-put",
            "edge": edge,
            "description": str(canonical_row.get("description") or ""),
            "observed_operation_ids": [],
        }
    event = {
        "schema_version": int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        "project_key": project_key,
        "operation_id": operation_id,
        "created_by": str(canonical_row.get("created_by") or ""),
        "origin": origin,
        "created_at": str(canonical_row.get("created_at") or ""),
        "kind": kind,
    }
    return _canonicalize_event(event)


def _canonicalize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return dict(require_rust_binding("artifact_link_event_canonicalize")(dict(event)))


def _rows_from_events(
    events: Iterable[Mapping[str, Any] | None],
) -> tuple[dict[str, Any], ...]:
    canonical_events = [dict(event) for event in events if event is not None]
    if not canonical_events:
        return ()
    reduction = require_rust_binding("artifact_link_events_reduce")(
        canonical_events,
        [],
    )
    if not isinstance(reduction, Mapping):
        raise RuntimeError("sase_core_rs returned malformed link-event reduction")
    rows = reduction.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("sase_core_rs returned malformed link-event rows")
    return tuple(
        validate_artifact_link_row(row) for row in rows if isinstance(row, dict)
    )


def _operation_id(value: object) -> str:
    text = _required_text(value, "operation_id")
    if len(text) != 32 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(
            "artifact-link outbox operation_id must be 32 lowercase hex characters"
        )
    return text


def _event_operation_id(event: Mapping[str, Any]) -> str:
    return _operation_id(event.get("operation_id"))


def _integer_schema_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError("artifact-link outbox schema_version must be an integer")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"artifact-link outbox {field} must be a non-empty string")
    return value.strip()


__all__ = [
    "ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME",
    "ARTIFACT_LINK_OUTBOX_FILENAME",
    "ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION",
    "append_artifact_link_outbox_event",
    "append_artifact_link_outbox_entry",
    "drain_artifact_link_outbox",
    "inspect_artifact_link_outbox",
    "pending_artifact_link_outbox_events",
]

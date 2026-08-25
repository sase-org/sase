"""Machine-local replay log for artifact-link read rows."""

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
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_store_support import (
    sidecar_index_path,
    validate_artifact_link_row,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore, resolve_artifact_link_store

ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION = 1
ARTIFACT_LINK_OUTBOX_FILENAME = "artifact-link-outbox.jsonl"
ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME = "artifact-link-outbox-dropped.jsonl"

_PUBLISHED_AGENT_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})
_TERMINAL_AGENT_STATES = frozenset({"completed", "failed", "stopped", "dismissed"})
_TERMINAL_AGENT_STATUSES = frozenset({"DONE", "FAILED", "STOPPED", "CANCELED"})
_SECONDS_PER_DAY = 24 * 60 * 60
_DEFAULT_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxEntry:
    """One queued artifact-link row plus its recording agent."""

    schema_version: int
    id: str
    created_at: float
    project_key: str
    agent_name: str
    row: dict[str, Any]

    @property
    def logical_key(self) -> tuple[str, str, str]:
        return _row_key(self.row)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "created_at": self.created_at,
            "project_key": self.project_key,
            "agent_name": self.agent_name,
            "row": dict(self.row),
        }


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
    row: Mapping[str, Any],
    now: float | None = None,
    entry_id: str | None = None,
) -> _ArtifactLinkOutboxEntry:
    """Append one replayable artifact-link row to the project outbox."""

    entry = _ArtifactLinkOutboxEntry(
        schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
        id=entry_id or uuid4().hex[:12],
        created_at=float(time.time() if now is None else now),
        project_key=project_key,
        agent_name=_required_text(agent_name, "agent_name"),
        row=validate_artifact_link_row(row),
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

    changed_indexes = _upsert_publishable_entries(link_store, publishable)
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
            )
    else:
        committed = False

    _rewrite_without_ids(
        link_store.project_key,
        drained_ids={entry.id for entry in publishable},
        dropped=stale,
    )
    return _ArtifactLinkOutboxDrainReport(
        queued=len(entries),
        drained=len(publishable),
        retained=len(entries) - len(publishable) - len(stale),
        dropped=len(stale),
        committed=committed,
        changed_indexes=tuple(changed_indexes),
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
            and not _agent_is_published(entry.agent_name)
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
        if _agent_is_published(entry.agent_name):
            publishable.append(entry)
        else:
            retained.append(entry)
    return publishable, retained


def _upsert_publishable_entries(
    store: ArtifactLinkStore,
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> list[Path]:
    changed_indexes: list[Path] = []
    for row in _converged_rows(store, entries):
        existing_uses = _existing_uses(store, row)
        desired_uses = _row_uses(row)
        if existing_uses >= desired_uses:
            changed_indexes.extend(_existing_index_paths(store, row))
            continue
        delta = dict(row)
        delta["uses"] = desired_uses - existing_uses
        outcome = store.upsert_row(delta)
        changed_indexes.extend(outcome.get("changed_indexes") or ())
    return list(dict.fromkeys(changed_indexes))


def _converged_rows(
    store: ArtifactLinkStore,
    entries: Iterable[_ArtifactLinkOutboxEntry],
) -> tuple[dict[str, Any], ...]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for entry in entries:
        key = entry.logical_key
        if key not in by_key:
            order.append(key)
            by_key[key] = dict(entry.row)
            continue
        current = by_key[key]
        if _row_uses(entry.row) >= _row_uses(current):
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
        mutation_origin="machine" if store.sdd_store is not None else "user",
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
    if data.get("schema_version") != ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION:
        raise RuntimeError("unsupported artifact-link outbox schema")
    entry_project = _required_text(data.get("project_key"), "project_key")
    if entry_project != project_key:
        raise RuntimeError("artifact-link outbox project mismatch")
    created_at = data.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        raise RuntimeError("artifact-link outbox created_at must be a number")
    row = data.get("row")
    if not isinstance(row, dict):
        raise RuntimeError("artifact-link outbox row must be an object")
    return _ArtifactLinkOutboxEntry(
        schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
        id=_required_text(data.get("id"), "id"),
        created_at=float(created_at),
        project_key=entry_project,
        agent_name=_required_text(data.get("agent_name"), "agent_name"),
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


def _agent_is_published(agent_name: str) -> bool:
    try:
        from sase.artifact_cli.references import resolve_cli_reference

        result = resolve_cli_reference(f"agent:{agent_name}")
    except Exception:  # noqa: BLE001 - unresolved agents stay queued.
        return False
    return result.resolution.status in _PUBLISHED_AGENT_STATUSES


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


def _row_uses(row: Mapping[str, Any]) -> int:
    try:
        uses = int(row.get("uses") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, uses)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"artifact-link outbox {field} must be a non-empty string")
    return value.strip()


__all__ = [
    "ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME",
    "ARTIFACT_LINK_OUTBOX_FILENAME",
    "ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION",
    "append_artifact_link_outbox_entry",
    "drain_artifact_link_outbox",
    "inspect_artifact_link_outbox",
]

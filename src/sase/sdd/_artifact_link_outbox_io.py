"""JSONL persistence for the artifact-link operation journal."""

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
from sase.sdd._artifact_link_outbox_stats import artifact_link_outbox_age_stats
from sase.sdd._artifact_link_outbox_types import (
    ARTIFACT_LINK_OUTBOX_DROPPED_FILENAME,
    ARTIFACT_LINK_OUTBOX_FILENAME,
    ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
    ArtifactLinkOutboxEntry as _ArtifactLinkOutboxEntry,
    entry_from_line as _entry_from_line,
    event_from_row as _event_from_row,
    event_operation_id as _event_operation_id,
    operation_id as _operation_id,
    required_text as _required_text,
    rows_from_events as _rows_from_events,
)
from sase.sdd._artifact_link_event_canonical import (
    canonical_artifact_link_event_object as _canonical_event_object,
)
from sase.sdd.artifact_link_event_publisher import (
    canonical_event as _canonical_event,
    stable_artifact_link_operation_id as _stable_operation_id,
)


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxStats:
    """Current queue depth, cumulative drops, and queued-event age spread."""

    queued: int
    dropped: int
    event_queued: int = 0
    oldest_age_seconds: float = 0.0
    newest_age_seconds: float = 0.0
    p95_age_seconds: float = 0.0


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

    parsed_operation_id = _operation_id(entry_id or uuid4().hex)
    event = _event_from_row(
        row,
        project_key=project_key,
        operation_id=parsed_operation_id,
    )
    [legacy_row] = _rows_from_events((event,))
    entry = _ArtifactLinkOutboxEntry(
        schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
        id=parsed_operation_id,
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
        _reject_outbox_operation_collision(
            path,
            project_key,
            operation_id=parsed_operation_id,
            event=event,
        )
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

    canonical = _canonical_event(event)
    parsed_operation_id = _event_operation_id(canonical)
    event_project = _required_text(canonical.get("project_key"), "project_key")
    if event_project != project_key:
        raise ValueError("artifact-link outbox event project mismatch")
    rows = _rows_from_events((canonical,))
    entry = _ArtifactLinkOutboxEntry(
        schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
        id=parsed_operation_id,
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
        _reject_outbox_operation_collision(
            path,
            project_key,
            operation_id=parsed_operation_id,
            event=canonical,
        )
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(entry.to_json_dict(), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()
    return entry


def read_artifact_link_outbox_entries(
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


def convert_legacy_artifact_link_outbox_entries(project_key: str) -> int:
    """Convert valid schema-v1 row-only outbox records to schema-v2 events."""

    path = _artifact_link_outbox_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        if not path.is_file():
            return 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        output_rows: list[dict[str, Any]] = []
        converted = 0
        for lineno, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"malformed artifact-link outbox JSON at line {lineno}"
                ) from exc
            if not isinstance(data, dict):
                raise RuntimeError(
                    f"artifact-link outbox line {lineno} must be an object"
                )
            if isinstance(data.get("event"), dict):
                entry = _entry_from_line(line, project_key)
                if entry is None:
                    raise RuntimeError(
                        f"malformed artifact-link event outbox entry at line {lineno}"
                    )
                output_rows.append(entry.to_json_dict())
                continue
            schema_version = data.get("schema_version")
            if schema_version != 1:
                raise RuntimeError(
                    "artifact-link outbox row-only entries must be schema-v1 "
                    f"for import conversion at line {lineno}"
                )
            entry_project = _required_text(data.get("project_key"), "project_key")
            if entry_project != project_key:
                raise RuntimeError("artifact-link outbox project mismatch")
            created_at = data.get("created_at")
            if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
                raise RuntimeError("artifact-link outbox created_at must be a number")
            row = data.get("row")
            if not isinstance(row, dict):
                raise RuntimeError("artifact-link outbox row must be an object")
            agent_name = _required_text(data.get("agent_name"), "agent_name")
            run_id = str(data.get("run_id") or "")
            operation_id = _stable_operation_id(
                "legacy-outbox-import",
                project_key,
                str(data.get("id") or ""),
                float(created_at),
                agent_name,
                run_id,
                row,
            )
            event = _event_from_row(
                row,
                project_key=project_key,
                operation_id=operation_id,
            )
            rows = _rows_from_events((event,))
            entry = _ArtifactLinkOutboxEntry(
                schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
                id=operation_id,
                created_at=float(created_at),
                project_key=project_key,
                agent_name=agent_name,
                run_id=run_id,
                row=rows[0] if len(rows) == 1 else None,
                event=event,
            )
            output_rows.append(entry.to_json_dict())
            converted += 1
        if converted:
            _write_jsonl(path, output_rows)
        return converted


def pending_artifact_link_outbox_events(
    project_key: str,
    *,
    exclude_operation_ids: Iterable[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Return queued schema-v2 events for local pending-link overlays."""

    excluded = _excluded_operation_ids(exclude_operation_ids)
    return tuple(
        dict(entry.event)
        for entry in read_artifact_link_outbox_entries(project_key)
        if entry.event is not None and entry.id not in excluded
    )


def pending_artifact_link_outbox_event_created_at(
    project_key: str,
    *,
    exclude_operation_ids: Iterable[str] = (),
) -> tuple[float, ...]:
    """Return queue timestamps for pending schema-v2 event entries."""

    excluded = _excluded_operation_ids(exclude_operation_ids)
    return tuple(
        entry.created_at
        for entry in read_artifact_link_outbox_entries(project_key)
        if entry.event is not None and entry.id not in excluded
    )


def inspect_artifact_link_outbox(
    project_key: str,
    *,
    now: float | None = None,
) -> _ArtifactLinkOutboxStats:
    """Return doctor-facing outbox queue, drop, and queue-age counts."""

    entries = read_artifact_link_outbox_entries(project_key)
    age_stats = artifact_link_outbox_age_stats(
        (entry.created_at for entry in entries),
        now=now,
    )
    return _ArtifactLinkOutboxStats(
        queued=len(entries),
        dropped=_count_jsonl_rows(_artifact_link_outbox_dropped_path(project_key)),
        event_queued=sum(1 for entry in entries if entry.event is not None),
        oldest_age_seconds=age_stats.oldest_age_seconds,
        newest_age_seconds=age_stats.newest_age_seconds,
        p95_age_seconds=age_stats.p95_age_seconds,
    )


def rewrite_artifact_link_outbox_without_ids(
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


def _reject_outbox_operation_collision(
    path: Path,
    project_key: str,
    *,
    operation_id: str,
    event: Mapping[str, Any],
) -> None:
    incoming = _canonical_event_object(event)
    for entry in _read_entries_unlocked(path, project_key):
        if entry.id != operation_id or entry.event is None:
            continue
        existing = _canonical_event_object(entry.event)
        if existing.payload != incoming.payload:
            raise RuntimeError(
                f"artifact-link outbox operation_id `{operation_id}` "
                "was reused for different event bytes"
            )


def _excluded_operation_ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value) for value in values if str(value))


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


__all__ = [
    "append_artifact_link_outbox_entry",
    "append_artifact_link_outbox_event",
    "convert_legacy_artifact_link_outbox_entries",
    "inspect_artifact_link_outbox",
    "pending_artifact_link_outbox_event_created_at",
    "pending_artifact_link_outbox_events",
    "read_artifact_link_outbox_entries",
    "rewrite_artifact_link_outbox_without_ids",
]

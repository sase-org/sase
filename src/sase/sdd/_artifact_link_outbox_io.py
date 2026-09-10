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
from sase.sdd.artifact_link_event_publisher import canonical_event as _canonical_event


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxStats:
    """Current queue depth plus cumulative drops."""

    queued: int
    dropped: int


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


def inspect_artifact_link_outbox(project_key: str) -> _ArtifactLinkOutboxStats:
    """Return doctor-facing outbox queue and drop counts."""

    return _ArtifactLinkOutboxStats(
        queued=len(read_artifact_link_outbox_entries(project_key)),
        dropped=_count_jsonl_rows(_artifact_link_outbox_dropped_path(project_key)),
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
    "inspect_artifact_link_outbox",
    "read_artifact_link_outbox_entries",
    "rewrite_artifact_link_outbox_without_ids",
]

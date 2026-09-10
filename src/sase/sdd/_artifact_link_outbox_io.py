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
from sase.core.rust import require_rust_binding
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
)


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxStats:
    """Current queue depth, cumulative drops, and queued-event age spread."""

    queued: int
    dropped: int
    event_queued: int = 0
    legacy_queued: int = 0
    invalid_queued: int = 0
    oldest_age_seconds: float = 0.0
    newest_age_seconds: float = 0.0
    p95_age_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxRecord:
    """One physical outbox line plus its parse/classification result."""

    line: str
    kind: str
    entry: _ArtifactLinkOutboxEntry | None = None
    diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxConversionReport:
    """Result of converting legacy row-only outbox records."""

    converted: int = 0
    covered: int = 0
    invalid: tuple[str, ...] = ()


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
            os.fsync(output_file.fileno())
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
            os.fsync(output_file.fileno())
    return entry


def read_artifact_link_outbox_entries(
    project_key: str,
) -> tuple[_ArtifactLinkOutboxEntry, ...]:
    """Read valid queued outbox entries, skipping malformed JSONL rows."""

    path = _artifact_link_outbox_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        return tuple(
            record.entry
            for record in _read_outbox_records_unlocked(path, project_key)
            if record.kind == "event" and record.entry is not None
        )


def convert_legacy_artifact_link_outbox_entries(
    project_key: str,
    *,
    baseline_rows: Iterable[Mapping[str, Any]] = (),
) -> _ArtifactLinkOutboxConversionReport:
    """Convert valid schema-v1 row-only outbox records to schema-v2 events."""

    path = _artifact_link_outbox_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        if not path.is_file():
            return _ArtifactLinkOutboxConversionReport()
        records = _read_outbox_records_unlocked(path, project_key)
        output_lines: list[str] = []
        covered_records: list[_ArtifactLinkOutboxRecord] = []
        converted = 0
        invalid: list[str] = []
        baseline = [dict(row) for row in baseline_rows]
        for lineno, record in enumerate(records, start=1):
            if record.kind == "event":
                output_lines.append(record.line)
                continue
            if record.kind == "invalid":
                output_lines.append(record.line)
                invalid.append(f"line {lineno}: {record.diagnostic or 'invalid'}")
                continue
            try:
                data = json.loads(record.line)
            except json.JSONDecodeError:
                output_lines.append(record.line)
                invalid.append(f"line {lineno}: invalid JSON")
                continue
            if not isinstance(data, dict):
                output_lines.append(record.line)
                invalid.append(
                    f"line {lineno}: artifact-link outbox line must be an object"
                )
                continue
            conversion = dict(
                require_rust_binding("artifact_link_outbox_legacy_conversion")(
                    data,
                    project_key,
                    baseline,
                )
            )
            outcome = str(conversion.get("outcome") or "")
            if outcome == "covered":
                covered_records.append(record)
                continue
            if outcome != "convert" or not isinstance(conversion.get("event"), dict):
                output_lines.append(record.line)
                invalid.append(
                    f"line {lineno}: unsupported legacy conversion outcome {outcome}"
                )
                continue
            agent_name = _required_text(data.get("agent_name"), "agent_name")
            run_id = str(data.get("run_id") or "")
            event = dict(conversion["event"])
            operation_id = _event_operation_id(event)
            rows = _rows_from_events((event,))
            entry = _ArtifactLinkOutboxEntry(
                schema_version=ARTIFACT_LINK_OUTBOX_SCHEMA_VERSION,
                id=operation_id,
                created_at=float(data["created_at"]),
                project_key=project_key,
                agent_name=agent_name,
                run_id=run_id,
                row=rows[0] if len(rows) == 1 else None,
                event=event,
            )
            output_lines.append(_jsonl_line(entry.to_json_dict()))
            converted += 1
        if converted or covered_records:
            _write_lines(path, output_lines)
        if covered_records:
            _append_dropped_records(
                project_key,
                covered_records,
                drop_reason="legacy_row_covered_by_baseline_import",
            )
        return _ArtifactLinkOutboxConversionReport(
            converted=converted,
            covered=len(covered_records),
            invalid=tuple(invalid),
        )


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

    records = _read_outbox_records(project_key)
    entries = tuple(record.entry for record in records if record.entry is not None)
    age_stats = artifact_link_outbox_age_stats(
        (entry.created_at for entry in entries),
        now=now,
    )
    return _ArtifactLinkOutboxStats(
        queued=len(entries),
        dropped=_count_jsonl_rows(_artifact_link_outbox_dropped_path(project_key)),
        event_queued=sum(1 for entry in entries if entry.event is not None),
        legacy_queued=sum(1 for record in records if record.kind == "legacy_row"),
        invalid_queued=sum(1 for record in records if record.kind == "invalid"),
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
        current = _read_outbox_records_unlocked(path, project_key)
        dropped_ids = {dropped_entry.id for dropped_entry in dropped}
        kept_lines: list[str] = []
        for record in current:
            if record.entry is None:
                kept_lines.append(record.line)
                continue
            if record.entry.id in drained_ids or record.entry.id in dropped_ids:
                continue
            kept_lines.append(record.line)
        _write_lines(path, kept_lines)
    if dropped:
        _append_dropped(project_key, dropped)


def _append_dropped(
    project_key: str,
    entries: Iterable[_ArtifactLinkOutboxEntry],
    *,
    drop_reason: str = "terminal_unpublished_retention_expired",
) -> None:
    path = _artifact_link_outbox_dropped_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            for entry in entries:
                payload = entry.to_json_dict()
                payload["dropped_at"] = time.time()
                payload["drop_reason"] = drop_reason
                json.dump(payload, output_file, sort_keys=True)
                output_file.write("\n")
            output_file.flush()
            os.fsync(output_file.fileno())


def _append_dropped_records(
    project_key: str,
    records: Iterable[_ArtifactLinkOutboxRecord],
    *,
    drop_reason: str,
) -> None:
    path = _artifact_link_outbox_dropped_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            for record in records:
                try:
                    payload = json.loads(record.line)
                except json.JSONDecodeError:
                    payload = {"line": record.line}
                if not isinstance(payload, dict):
                    payload = {"line": record.line}
                payload["dropped_at"] = time.time()
                payload["drop_reason"] = drop_reason
                json.dump(payload, output_file, sort_keys=True)
                output_file.write("\n")
            output_file.flush()
            os.fsync(output_file.fileno())


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as output_file:
            for line in lines:
                output_file.write(line)
                output_file.write("\n")
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _read_entries_unlocked(
    path: Path, project_key: str
) -> tuple[_ArtifactLinkOutboxEntry, ...]:
    return tuple(
        record.entry
        for record in _read_outbox_records_unlocked(path, project_key)
        if record.entry is not None
    )


def _read_outbox_records(project_key: str) -> tuple[_ArtifactLinkOutboxRecord, ...]:
    path = _artifact_link_outbox_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        return _read_outbox_records_unlocked(path, project_key)


def _read_outbox_records_unlocked(
    path: Path,
    project_key: str,
) -> tuple[_ArtifactLinkOutboxRecord, ...]:
    if not path.is_file():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    records: list[_ArtifactLinkOutboxRecord] = []
    for line in lines:
        if not line.strip():
            continue
        classified = dict(
            require_rust_binding("artifact_link_outbox_classify_line")(
                line,
                project_key,
            )
        )
        kind = str(classified.get("kind") or "invalid")
        entry = _entry_from_line(line, project_key) if kind == "event" else None
        if kind == "event" and entry is None:
            kind = "invalid"
        records.append(
            _ArtifactLinkOutboxRecord(
                line=line,
                kind=kind,
                entry=entry,
                diagnostic=(
                    None
                    if classified.get("diagnostic") is None
                    else str(classified.get("diagnostic"))
                ),
            )
        )
    return tuple(records)


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


def _jsonl_line(row: Mapping[str, Any]) -> str:
    return json.dumps(dict(row), sort_keys=True)


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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

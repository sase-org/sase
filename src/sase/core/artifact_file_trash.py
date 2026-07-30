"""Restorable artifact-file trash and index coordination."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sase.core.artifact_file_economics import (
    ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
)
from sase.core.artifact_file_explicit import (
    artifact_file_index_lock,
    read_artifact_file_index_document_unlocked,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_types import (
    ArtifactFile,
    artifact_file_from_dict,
    artifact_file_to_dict,
    default_artifact_files_index_path,
)
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class TrashEntry:
    """One restorable entry in the artifact trash."""

    entry_id: str
    artifact_id: str
    trashed_at: str
    reason: str
    size_bytes: int | None
    stored_filename: str | None
    stored_path: str | None
    record: ArtifactFile

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe entry projection."""

        payload = asdict(self)
        payload["record"] = artifact_file_to_dict(self.record)
        return payload


@dataclass(frozen=True)
class _TrashListResult:
    """Validated trash listing returned by the core binding."""

    entries: tuple[TrashEntry, ...]
    unreadable_entries: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "entries": [entry.to_json_dict() for entry in self.entries],
            "unreadable_entries": self.unreadable_entries,
        }


@dataclass(frozen=True)
class TrashResult:
    """Rows successfully moved out of the live artifact index."""

    entries: tuple[TrashEntry, ...]
    rows_trashed: int
    bytes_reclaimed: int
    trash_root: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "entries": [entry.to_json_dict() for entry in self.entries],
            "rows_trashed": self.rows_trashed,
            "bytes_reclaimed": self.bytes_reclaimed,
            "trash_root": self.trash_root,
        }


@dataclass(frozen=True)
class _TrashRestoreResult:
    """One payload and complete index row restored from trash."""

    entry_id: str
    artifact_id: str
    restored_path: str | None
    index_path: str
    record: ArtifactFile

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["record"] = artifact_file_to_dict(self.record)
        return payload


@dataclass(frozen=True)
class _TrashPurgeResult:
    """Irreversible purge result returned by the core binding."""

    purged_entry_ids: tuple[str, ...]
    freed_bytes: int
    unreadable_entries: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def trash_artifact_files(
    rows: Sequence[ArtifactFile],
    *,
    reason: str,
    now: str | None = None,
    index_path: Path | str | None = None,
) -> TrashResult:
    """Move rows to restorable trash and remove them from the live index.

    One exclusive index lock covers the batch. Each successful core move is
    followed immediately by an index rewrite, so an interrupted batch leaves
    either a live row or a restorable trash entry for every payload.
    """

    if not reason.strip():
        raise ValueError("trash reason must not be empty")
    requested = tuple(rows)
    requested_ids = [row.id for row in requested]
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("trash batch contains duplicate artifact ids")

    _require_lifecycle_schema()
    idx = _resolved_index_path(index_path)
    trash_root = _trash_root(idx)
    trashed_at = now or datetime.now(UTC).isoformat()
    store = require_rust_binding("artifact_file_trash_store")
    entries: list[TrashEntry] = []

    with artifact_file_index_lock(idx, exclusive=True):
        current_rows, preserved_lines = read_artifact_file_index_document_unlocked(idx)
        rows_by_id = {row.id: row for row in current_rows}
        for requested_row in requested:
            current = rows_by_id.get(requested_row.id)
            if current is None:
                raise RuntimeError(
                    f"artifact row disappeared before trashing: {requested_row.id}"
                )
            if current != requested_row:
                raise RuntimeError(
                    f"artifact row changed before trashing: {requested_row.id}"
                )
            raw = store(
                {
                    "schema_version": ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
                    "trash_root": str(trash_root),
                    "record": artifact_file_to_dict(current),
                    "stored_path": current.path,
                    "reason": reason,
                    "trashed_at": trashed_at,
                }
            )
            entry = _entry_from_wire(raw, "trash store")
            if entry.artifact_id != current.id:
                raise _wire_error(
                    "trash store",
                    "artifact_id does not match the requested row",
                )
            entries.append(entry)
            del rows_by_id[current.id]
            current_rows = [row for row in current_rows if row.id != current.id]
            write_artifact_file_index_unlocked(
                idx,
                current_rows,
                preserved_lines=preserved_lines,
            )

    return TrashResult(
        entries=tuple(entries),
        rows_trashed=len(entries),
        bytes_reclaimed=sum(entry.size_bytes or 0 for entry in entries),
        trash_root=str(trash_root),
    )


def list_trashed_artifact_files(
    *,
    index_path: Path | str | None = None,
) -> _TrashListResult:
    """List restorable entries newest first."""

    _require_lifecycle_schema()
    idx = _resolved_index_path(index_path)
    binding = require_rust_binding("artifact_file_trash_list")
    data = _mapping(binding(str(_trash_root(idx))), "trash list", "result")
    _schema(data, "trash list")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise _wire_error("trash list", "entries must be a list")
    return _TrashListResult(
        entries=tuple(
            _entry_from_wire(item, f"trash list entries[{index}]")
            for index, item in enumerate(raw_entries, start=1)
        ),
        unreadable_entries=_nonnegative_integer(
            data,
            "unreadable_entries",
            "trash list",
        ),
    )


def restore_trashed_artifact_file(
    entry_id: str,
    *,
    index_path: Path | str | None = None,
) -> _TrashRestoreResult:
    """Restore one trash payload, then reinsert its complete original row."""

    if not entry_id.strip():
        raise ValueError("trash entry id must not be empty")
    _require_lifecycle_schema()
    idx = _resolved_index_path(index_path)
    restore = require_rust_binding("artifact_file_trash_restore")

    with artifact_file_index_lock(idx, exclusive=True):
        raw = restore(
            {
                "schema_version": ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
                "trash_root": str(_trash_root(idx)),
                "entry_id": entry_id,
            }
        )
        data = _mapping(raw, "trash restore", "result")
        _schema(data, "trash restore")
        restored_entry_id = _string(data, "entry_id", "trash restore")
        artifact_id = _string(data, "artifact_id", "trash restore")
        restored_path = _optional_string(data, "restored_path", "trash restore")
        record = _record(data.get("record"), "trash restore")
        if restored_entry_id != entry_id:
            raise _wire_error(
                "trash restore",
                "entry_id does not match the requested entry",
            )
        if artifact_id != record.id:
            raise _wire_error(
                "trash restore",
                "artifact_id does not match record.id",
            )

        rows, preserved_lines = read_artifact_file_index_document_unlocked(idx)
        rows_by_id = {row.id: row for row in rows}
        rows_by_id[record.id] = record
        write_artifact_file_index_unlocked(
            idx,
            list(rows_by_id.values()),
            preserved_lines=preserved_lines,
        )

    return _TrashRestoreResult(
        entry_id=restored_entry_id,
        artifact_id=artifact_id,
        restored_path=restored_path,
        index_path=str(idx),
        record=record,
    )


def purge_trashed_artifact_files(
    *,
    before: str | None = None,
    purge_all: bool = False,
    index_path: Path | str | None = None,
) -> _TrashPurgeResult:
    """Permanently purge entries before a cutoff or every entry explicitly."""

    _require_lifecycle_schema()
    idx = _resolved_index_path(index_path)
    from sase.config import get_artifact_retention_trash_grace_days

    cutoff = (
        before
        or (
            datetime.now(UTC)
            - timedelta(days=get_artifact_retention_trash_grace_days())
        ).isoformat()
    )
    purge = require_rust_binding("artifact_file_trash_purge")
    data = _mapping(
        purge(
            {
                "schema_version": ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
                "trash_root": str(_trash_root(idx)),
                "before": cutoff,
                "all": purge_all,
            }
        ),
        "trash purge",
        "result",
    )
    _schema(data, "trash purge")
    raw_ids = data.get("purged_entry_ids")
    if not isinstance(raw_ids, list) or not all(
        isinstance(item, str) for item in raw_ids
    ):
        raise _wire_error("trash purge", "purged_entry_ids must be a list of strings")
    return _TrashPurgeResult(
        purged_entry_ids=tuple(raw_ids),
        freed_bytes=_nonnegative_integer(data, "freed_bytes", "trash purge"),
        unreadable_entries=_nonnegative_integer(
            data,
            "unreadable_entries",
            "trash purge",
        ),
    )


def _resolved_index_path(index_path: Path | str | None) -> Path:
    return (
        Path(default_artifact_files_index_path() if index_path is None else index_path)
        .expanduser()
        .resolve(strict=False)
    )


def _trash_root(index_path: Path) -> Path:
    return index_path.parent / "trash"


def _require_lifecycle_schema() -> None:
    binding = require_rust_binding("artifact_file_lifecycle_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-file lifecycle wire is stale: "
            f"expected {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _entry_from_wire(raw: object, operation: str) -> TrashEntry:
    data = _mapping(raw, operation, "result")
    _schema(data, operation)
    record = _record(data.get("record"), operation)
    artifact_id = _string(data, "artifact_id", operation)
    if record.id != artifact_id:
        raise _wire_error(operation, "record.id does not match artifact_id")
    return TrashEntry(
        entry_id=_string(data, "entry_id", operation),
        artifact_id=artifact_id,
        trashed_at=_string(data, "trashed_at", operation),
        reason=_string(data, "reason", operation),
        size_bytes=_optional_nonnegative_integer(data, "size_bytes", operation),
        stored_filename=_optional_string(data, "stored_filename", operation),
        stored_path=_optional_string(data, "stored_path", operation),
        record=record,
    )


def _record(raw: object, operation: str) -> ArtifactFile:
    if not isinstance(raw, Mapping):
        raise _wire_error(operation, "record must be an object")
    try:
        return artifact_file_from_dict(dict(cast(Mapping[str, Any], raw)))
    except (KeyError, TypeError, ValueError) as exc:
        raise _wire_error(operation, f"record is invalid: {exc}") from exc


def _mapping(
    raw: object,
    operation: str,
    field: str,
) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise _wire_error(operation, f"{field} must be an object")
    return cast(Mapping[str, Any], raw)


def _schema(data: Mapping[str, Any], operation: str) -> None:
    version = _nonnegative_integer(data, "schema_version", operation)
    if version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise _wire_error(
            operation,
            f"schema_version must be {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}",
        )


def _string(data: Mapping[str, Any], field: str, operation: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise _wire_error(operation, f"{field} must be a string")
    return value


def _optional_string(
    data: Mapping[str, Any],
    field: str,
    operation: str,
) -> str | None:
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise _wire_error(operation, f"{field} must be a string or null")
    return value


def _nonnegative_integer(
    data: Mapping[str, Any],
    field: str,
    operation: str,
) -> int:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _wire_error(operation, f"{field} must be a non-negative integer")
    return value


def _optional_nonnegative_integer(
    data: Mapping[str, Any],
    field: str,
    operation: str,
) -> int | None:
    if data.get(field) is None:
        return None
    return _nonnegative_integer(data, field, operation)


def _wire_error(operation: str, detail: str) -> RuntimeError:
    return RuntimeError(
        f"sase_core_rs returned an incompatible artifact-file {operation}: {detail}"
    )


__all__ = [
    "TrashEntry",
    "TrashResult",
    "list_trashed_artifact_files",
    "purge_trashed_artifact_files",
    "restore_trashed_artifact_file",
    "trash_artifact_files",
]

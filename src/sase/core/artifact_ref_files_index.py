"""Durable version index for file-backed artifact references."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Any, cast
from collections.abc import Iterable, Mapping

from sase.core.artifact_file_facade import default_artifact_files_root
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file


REF_FILES_INDEX_NAME = "ref-files.jsonl"


def default_ref_files_index_path() -> Path:
    """Return the default sibling index for file-reference versions."""

    return default_artifact_files_root() / REF_FILES_INDEX_NAME


def upsert_ref_file_versions(
    records: Iterable[Mapping[str, Any]],
    *,
    index_path: Path | str | None = None,
    agent_name: str | None = None,
    project: str | None = None,
    sidecar_repo: str | None = None,
) -> int:
    """Append published file-reference version rows.

    The JSONL log is append-only. Repeated ``(logical_path, sha256)`` rows add
    provenance that the Rust fold collapses for readers.
    """

    path = (
        Path(index_path).expanduser().resolve(strict=False)
        if index_path is not None
        else default_ref_files_index_path()
    )
    rows = [
        row
        for record in records
        if (row := _row_for_record(record, agent_name, project, sidecar_repo))
        is not None
    ]
    if not rows:
        return 0
    render = require_rust_binding("artifact_ref_file_row_render")
    validate = require_rust_binding("artifact_ref_file_row_validate")
    lines: list[str] = []
    for row in rows:
        validate(dict(row))
        lines.append(str(render(dict(row))))
    lock_path = path.with_suffix(".lock")
    with locked_file(lock_path, fcntl.LOCK_EX):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for line in lines:
                stream.write(line)
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return len(lines)


def query_ref_file_versions(
    *,
    index_path: Path | str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Return folded logical-file projections from the ref-files index."""

    path = (
        Path(index_path).expanduser().resolve(strict=False)
        if index_path is not None
        else default_ref_files_index_path()
    )
    if not path.is_file():
        return ()
    parse = require_rust_binding("artifact_ref_file_index_parse")
    fold = require_rust_binding("artifact_ref_files_fold")
    rows = parse(path.read_bytes())
    return tuple(cast(list[Mapping[str, Any]], fold(rows)))


def _row_for_record(
    record: Mapping[str, Any],
    agent_name: str | None,
    project: str | None,
    sidecar_repo: str | None,
) -> dict[str, Any] | None:
    sha256 = _str(record.get("sha256"))
    size_bytes = record.get("size_bytes")
    if sha256 is None or not isinstance(size_bytes, int):
        return None
    pool_relpath = _str(record.get("pool_relpath"))
    if pool_relpath is None:
        return None
    origin = _str(record.get("origin")) or _origin_for_record(record)
    artifact_id = _artifact_id_for_record(record) if origin == "created" else None
    logical_path = _str(record.get("logical_path"))
    if logical_path is None:
        logical_path = _str(record.get("source_path")) or (
            f"artifact:{artifact_id}" if artifact_id else None
        )
    if logical_path is None:
        return None
    object_relpath = _str(record.get("object_relpath")) or str(
        require_rust_binding("artifact_object_relpath")(sha256)
    )
    schema_version = int(
        require_rust_binding("artifact_ref_file_index_wire_schema_version")()
    )
    return {
        "schema_version": schema_version,
        "logical_path": logical_path,
        "root_name": _str(record.get("root_name")),
        "authored_path": _str(record.get("authored_path")),
        "artifact_id": artifact_id,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "mime_type": _str(record.get("mime_type")),
        "first_seen_at": _str(record.get("recorded_at")) or "",
        "origin": origin,
        "object_relpath": object_relpath,
        "sidecar_repo": sidecar_repo,
        "agents": [] if agent_name is None else [agent_name],
        "projects": [] if project is None else [project],
    }


def _origin_for_record(record: Mapping[str, Any]) -> str:
    if _artifact_id_for_record(record) is not None:
        return "created"
    return "capture"


def _artifact_id_for_record(record: Mapping[str, Any]) -> str | None:
    raw_ref = _str(record.get("raw_ref")) or ""
    prefix = "@file:"
    if not raw_ref.startswith(prefix):
        return None
    payload = raw_ref.removeprefix(prefix).split("#", 1)[0]
    source, separator, digest = payload.partition(":")
    if separator and source in {"explicit", "default"} and digest:
        return f"{source}:{digest}"
    return None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "REF_FILES_INDEX_NAME",
    "default_ref_files_index_path",
    "query_ref_file_versions",
    "upsert_ref_file_versions",
]

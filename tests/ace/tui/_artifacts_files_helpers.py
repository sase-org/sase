"""Fixtures for the Artifacts Files pane tests."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.widgets.artifacts.files_data import (
    FilesSnapshot,
    LogicalFile,
    _files_snapshot,
    _logical_file,
    _version_from_legacy_row,
)
from sase.core.artifact_file_types import ArtifactFile


def artifact_file(
    name: str,
    *,
    artifact_id: str | None = None,
    kind: str = "file",
    path: str | None = None,
    created_at: str | None = "2026-07-24T14:32:00-04:00",
    project: str | None = "alpha",
    agent_name: str | None = "alpha.1--code",
    workflow: str | None = "code",
    explicit: bool = False,
    size_bytes: int | None = 12_697,
    **overrides: Any,
) -> ArtifactFile:
    values: dict[str, Any] = {
        "id": artifact_id or f"default:{name:0<24}"[:32],
        "label": f"{name} artifact",
        "kind": kind,
        "path": path or f"/tmp/{name}.txt",
        "created_at": created_at,
        "project": project,
        "agent_name": agent_name,
        "workflow": workflow,
        "explicit": explicit,
        "size_bytes": size_bytes,
    }
    values.update(overrides)
    return ArtifactFile(**values)


def logical_file(row: ArtifactFile) -> LogicalFile:
    version = _version_from_legacy_row(row)
    return _logical_file(version.logical_id, [version])


def snapshot(
    rows: tuple[ArtifactFile | LogicalFile, ...],
    *,
    project: str | None = "alpha",
    complete: bool = True,
    load_error: str | None = None,
) -> FilesSnapshot:
    return _files_snapshot(
        tuple(
            row if isinstance(row, LogicalFile) else logical_file(row) for row in rows
        ),
        project=project,
        complete=complete,
        load_error=load_error,
    )


__all__ = ["artifact_file", "logical_file", "snapshot"]

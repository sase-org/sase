"""Shared artifact-file path resolution for clipboard actions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, cast

from sase.core.artifact_file_types import ArtifactFile


@dataclass(frozen=True, slots=True)
class ArtifactFilePathCopy:
    """One anchored path answer and the artifact-file field it came from."""

    text: str
    origin: str
    missing: bool = False

    @property
    def label(self) -> str:
        return "stored path" if self.origin == "stored" else "source path"


def artifact_file_preferred_path_text(artifact_file: Any) -> tuple[str, str]:
    """Return the indexed path the ``Y`` verb prefers, without touching disk.

    Stored paths are preferred, except that PDF records deliberately point back
    to their live Markdown source when one is recorded. Byte-free rows expose
    their VCS-relative path until a worker materializes them. Anchoring,
    materialization, and liveness need :func:`artifact_file_clipboard_path`.
    """

    stored_text = str(getattr(artifact_file, "path", "") or "")
    source_text = str(getattr(artifact_file, "source_path", "") or "")
    prefers_source = bool(source_text and getattr(artifact_file, "kind", None) == "pdf")
    if prefers_source:
        return source_text, "source"
    if stored_text:
        return stored_text, "stored"
    vcs_relpath = str(getattr(artifact_file, "vcs_relpath", "") or "")
    if vcs_relpath:
        return vcs_relpath, "vcs"
    return source_text, "source"


def artifact_file_has_stored_content(artifact_file: Any) -> bool:
    """Return whether a row has stored bytes or complete VCS provenance."""

    return bool(
        getattr(artifact_file, "path", None)
        or all(
            getattr(artifact_file, field, None)
            for field in ("vcs_repo", "vcs_sha", "vcs_relpath")
        )
    )


def artifact_file_clipboard_path(
    artifact_file: Any,
) -> ArtifactFilePathCopy | None:
    """Return the preferred anchored path copied by the artifact-file ``Y`` verb.

    Stored paths are preferred, except that PDF records deliberately point back
    to their live Markdown source when one is recorded. Relative paths are
    anchored to the producing workspace, including legacy rows whose workspace
    is discoverable only through the agent artifact metadata.
    """

    path_text, origin = artifact_file_preferred_path_text(artifact_file)
    if origin != "vcs":
        return _path_copy(artifact_file, path_text, origin=origin)
    resolved = materialize_artifact_file_entry(cast(ArtifactFile, artifact_file))
    path_text, origin = artifact_file_preferred_path_text(resolved)
    return _path_copy(resolved, path_text, origin=origin)


def artifact_file_source_clipboard_path(
    artifact_file: Any,
) -> ArtifactFilePathCopy | None:
    """Return an explicitly requested, anchored source path."""

    source_text = str(getattr(artifact_file, "source_path", "") or "")
    return _path_copy(artifact_file, source_text, origin="source")


def _artifact_file_resolved_stored_path(artifact_file: Any) -> Path | None:
    """Resolve the indexed stored path without requiring it to exist."""

    path_text = str(getattr(artifact_file, "path", "") or "")
    if not path_text:
        return None
    return _resolve_artifact_file_path(
        path_text,
        workspace_dir=artifact_file_clipboard_workspace_dir(artifact_file),
    )


def artifact_file_materialized_stored_path(artifact_file: Any) -> Path | None:
    """Resolve stored bytes, materializing a VCS-backed row when necessary."""

    resolved = artifact_file
    if not getattr(artifact_file, "path", None) and artifact_file_has_stored_content(
        artifact_file
    ):
        resolved = materialize_artifact_file_entry(cast(ArtifactFile, artifact_file))
    return _artifact_file_resolved_stored_path(resolved)


def artifact_file_materialized_display_path(artifact_file: Any) -> Path | None:
    """Resolve copyable text, preserving a PDF row's Markdown-source preference."""

    path_text, origin = artifact_file_preferred_path_text(artifact_file)
    if origin == "source":
        if not path_text:
            return None
        return _resolve_artifact_file_path(
            path_text,
            workspace_dir=artifact_file_clipboard_workspace_dir(artifact_file),
        )
    return artifact_file_materialized_stored_path(artifact_file)


def materialize_artifact_file_entry(entry: ArtifactFile) -> ArtifactFile:
    """Resolve one row to bytes; safe to call only from a worker thread."""

    return materialize_artifact_file_entries((entry,))[0]


def materialize_artifact_file_entries(
    entries: Iterable[ArtifactFile],
) -> tuple[ArtifactFile, ...]:
    """Resolve rows through the shared launch repository context."""

    from sase.artifact_ref_context import launch_artifact_ref_context
    from sase.core.artifact_file_vcs import materialize_artifact_file

    accepted = tuple(entries)
    if all(entry.path for entry in accepted):
        return accepted
    context = launch_artifact_ref_context(is_home_mode=False)
    materialized: list[ArtifactFile] = []
    for entry in accepted:
        path = materialize_artifact_file(entry, repositories=context.repositories)
        if path is None:
            locator = (
                f"{entry.vcs_repo}@{entry.vcs_sha}:{entry.vcs_relpath}"
                if entry.is_vcs_backed
                else entry.id
            )
            raise OSError(f"content unavailable for {locator}")
        materialized.append(replace(entry, path=str(path)))
    return tuple(materialized)


def artifact_file_clipboard_workspace_dir(artifact_file: Any) -> str | None:
    """Return the workspace anchor recorded directly or in agent metadata."""

    workspace_dir = getattr(artifact_file, "workspace_dir", None)
    if isinstance(workspace_dir, str) and workspace_dir:
        return workspace_dir

    agent_artifacts_dir = getattr(artifact_file, "agent_artifacts_dir", None)
    if not isinstance(agent_artifacts_dir, str) or not agent_artifacts_dir:
        return None

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    for filename in ("done.json", "agent_meta.json"):
        data = _read_json_object(artifacts_dir / filename)
        workspace_dir = data.get("workspace_dir")
        if isinstance(workspace_dir, str) and workspace_dir:
            return workspace_dir
    return None


def _path_copy(
    artifact_file: Any,
    path_text: str,
    *,
    origin: str,
) -> ArtifactFilePathCopy | None:
    if not path_text:
        return None
    path = _resolve_artifact_file_path(
        path_text,
        workspace_dir=artifact_file_clipboard_workspace_dir(artifact_file),
    )
    missing = origin == "source" and not path.exists()
    return ArtifactFilePathCopy(_anchored_path(path), origin, missing)


def _resolve_artifact_file_path(
    path_text: str,
    *,
    workspace_dir: str | None,
) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute() and workspace_dir:
        path = Path(workspace_dir).expanduser() / path
    return path


def _anchored_path(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=False)
    try:
        relative = resolved.relative_to(Path.home().resolve(strict=False))
    except (OSError, ValueError):
        return str(resolved)
    text = relative.as_posix()
    return "~" if not text else f"~/{text}"


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = [
    "ArtifactFilePathCopy",
    "artifact_file_clipboard_path",
    "artifact_file_clipboard_workspace_dir",
    "artifact_file_has_stored_content",
    "artifact_file_materialized_display_path",
    "artifact_file_materialized_stored_path",
    "artifact_file_preferred_path_text",
    "artifact_file_source_clipboard_path",
    "materialize_artifact_file_entries",
    "materialize_artifact_file_entry",
]

"""Shared artifact-file path resolution for clipboard actions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


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
    to their live Markdown source when one is recorded. Surfaces that only name
    or preview the path use this, so they cannot disagree with what a copy
    yields; anchoring and liveness need :func:`artifact_file_clipboard_path`.
    """

    stored_text = str(getattr(artifact_file, "path", "") or "")
    source_text = str(getattr(artifact_file, "source_path", "") or "")
    prefers_source = bool(source_text and getattr(artifact_file, "kind", None) == "pdf")
    if prefers_source or not stored_text:
        return source_text, "source"
    return stored_text, "stored"


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
    return _path_copy(artifact_file, path_text, origin=origin)


def artifact_file_source_clipboard_path(
    artifact_file: Any,
) -> ArtifactFilePathCopy | None:
    """Return an explicitly requested, anchored source path."""

    source_text = str(getattr(artifact_file, "source_path", "") or "")
    return _path_copy(artifact_file, source_text, origin="source")


def artifact_file_resolved_stored_path(artifact_file: Any) -> Path | None:
    """Resolve the indexed stored path without requiring it to exist."""

    path_text = str(getattr(artifact_file, "path", "") or "")
    if not path_text:
        return None
    return _resolve_artifact_file_path(
        path_text,
        workspace_dir=artifact_file_clipboard_workspace_dir(artifact_file),
    )


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
    "artifact_file_preferred_path_text",
    "artifact_file_resolved_stored_path",
    "artifact_file_source_clipboard_path",
]

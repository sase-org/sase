"""Shared artifact-file models and serialization helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import sase_home as _sase_home

ArtifactFileKind = Literal["chat", "plan", "image", "markdown", "pdf", "file"]

# The version written by this package. Keep this at v1 while older SASE
# installations may still rewrite the shared index.
ARTIFACT_FILE_INDEX_SCHEMA_VERSION = 1
# Versions this package can safely deserialize and rewrite.
ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
ARTIFACT_FILE_KINDS: tuple[ArtifactFileKind, ...] = (
    "chat",
    "plan",
    "image",
    "markdown",
    "pdf",
    "file",
)

_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_JSONL_INDEX_NAME = "index.jsonl"
_LOCK_NAME = "index.lock"


@dataclass(frozen=True)
class ArtifactFileAssociation:
    """Stable identity for artifact files associated with one agent run."""

    agent_artifacts_dir: str
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = None
    agent_name: str | None = None


@dataclass(frozen=True)
class ArtifactFile:
    """One artifact file available for a SASE agent."""

    id: str
    label: str
    kind: ArtifactFileKind
    path: str
    source_path: str | None = None
    workspace_dir: str | None = None
    created_at: str | None = None
    agent_artifacts_dir: str | None = None
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = None
    agent_name: str | None = None
    explicit: bool = False
    sha256: str | None = None
    size_bytes: int | None = None
    mime_type: str | None = None


def default_artifact_files_root(sase_home: Path | str | None = None) -> Path:
    """Return the directory used for explicit user/agent artifact files."""

    root = Path(sase_home).expanduser() if sase_home is not None else _sase_home()
    return root / "artifacts"


def default_artifact_files_index_path(sase_home: Path | str | None = None) -> Path:
    """Return the JSONL index path for explicit agent artifact files."""

    return default_artifact_files_root(sase_home) / _JSONL_INDEX_NAME


def artifact_file_to_dict(artifact_file: ArtifactFile) -> dict[str, Any]:
    """Project an artifact-file model to a JSON-safe dict."""

    return asdict(artifact_file)


def artifact_file_from_dict(data: dict[str, Any]) -> ArtifactFile:
    """Rehydrate an artifact-file model from a JSON-safe dict."""

    kind = coerce_artifact_file_kind(data.get("kind"))
    return ArtifactFile(
        id=str(data["id"]),
        label=str(data["label"]),
        kind=kind,
        path=str(data["path"]),
        source_path=_optional_str(data.get("source_path")),
        workspace_dir=_optional_str(data.get("workspace_dir")),
        created_at=_optional_str(data.get("created_at")),
        agent_artifacts_dir=_optional_str(data.get("agent_artifacts_dir")),
        project=_optional_str(data.get("project")),
        workflow=_optional_str(data.get("workflow")),
        raw_timestamp=_optional_str(data.get("raw_timestamp")),
        agent_name=_optional_str(data.get("agent_name")),
        explicit=bool(data.get("explicit", False)),
        sha256=_optional_str(data.get("sha256")),
        size_bytes=_optional_int(data.get("size_bytes")),
        mime_type=_optional_str(data.get("mime_type")),
    )


def artifact_file_association_from_dir(
    agent_artifacts_dir: Path | str,
    *,
    agent_name: str | None = None,
) -> ArtifactFileAssociation:
    """Derive stable agent association fields from an artifact directory path."""

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = artifacts_dir.name or None
    info = parse_agent_artifact_path(artifacts_dir)
    if info is not None:
        project = info.project_name
        workflow = info.workflow_dir_name
        raw_timestamp = info.timestamp
    else:
        parts = artifacts_dir.parts
        for index, part in enumerate(parts):
            if part == "projects" and len(parts) > index + 4:
                project = parts[index + 1]
                if parts[index + 2] == "artifacts":
                    workflow = parts[index + 3]
                    raw_timestamp = parts[index + 4]
                break
    return ArtifactFileAssociation(
        agent_artifacts_dir=str(artifacts_dir),
        project=project,
        workflow=workflow,
        raw_timestamp=raw_timestamp,
        agent_name=agent_name,
    )


def infer_artifact_file_kind(path: Path | str) -> ArtifactFileKind:
    """Infer an artifact-file kind from a path suffix."""

    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    return "file"


def coerce_artifact_file_kind(kind: Any) -> ArtifactFileKind:
    if kind in ARTIFACT_FILE_KINDS:
        return kind
    raise ValueError(f"unsupported artifact-file kind: {kind!r}")


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None

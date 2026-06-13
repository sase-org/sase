"""Shared agent artifact models and serialization helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import sase_home as _sase_home

AgentArtifactKind = Literal["chat", "plan", "image", "markdown", "pdf", "file"]

AGENT_ARTIFACT_INDEX_SCHEMA_VERSION = 1
AGENT_ARTIFACT_KINDS: tuple[AgentArtifactKind, ...] = (
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
class AgentArtifactAssociation:
    """Stable identity for artifacts associated with one agent run."""

    agent_artifacts_dir: str
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = None
    agent_name: str | None = None


@dataclass(frozen=True)
class AgentArtifact:
    """One artifact available for a SASE agent."""

    id: str
    label: str
    kind: AgentArtifactKind
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


def default_artifacts_root(sase_home: Path | str | None = None) -> Path:
    """Return the directory used for explicit user/agent artifacts."""

    root = Path(sase_home).expanduser() if sase_home is not None else _sase_home()
    return root / "artifacts"


def default_agent_artifacts_index_path(sase_home: Path | str | None = None) -> Path:
    """Return the JSONL index path for explicit agent artifacts."""

    return default_artifacts_root(sase_home) / _JSONL_INDEX_NAME


def agent_artifact_to_dict(artifact: AgentArtifact) -> dict[str, Any]:
    """Project an artifact model to a JSON-safe dict."""

    return asdict(artifact)


def agent_artifact_from_dict(data: dict[str, Any]) -> AgentArtifact:
    """Rehydrate an artifact model from a JSON-safe dict."""

    kind = coerce_artifact_kind(data.get("kind"))
    return AgentArtifact(
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
    )


def artifact_association_from_dir(
    agent_artifacts_dir: Path | str,
    *,
    agent_name: str | None = None,
) -> AgentArtifactAssociation:
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
    return AgentArtifactAssociation(
        agent_artifacts_dir=str(artifacts_dir),
        project=project,
        workflow=workflow,
        raw_timestamp=raw_timestamp,
        agent_name=agent_name,
    )


def infer_artifact_kind(path: Path | str) -> AgentArtifactKind:
    """Infer an artifact kind from a path suffix."""

    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    return "file"


def coerce_artifact_kind(kind: Any) -> AgentArtifactKind:
    if kind in AGENT_ARTIFACT_KINDS:
        return kind
    raise ValueError(f"unsupported artifact kind: {kind!r}")


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None

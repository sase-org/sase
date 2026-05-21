"""Artifact normalization helpers for terminal viewer launches."""

from __future__ import annotations

from pathlib import Path

from ._viewer_types import ArtifactLike, ArtifactViewSpec

_MARKDOWN_SOURCE_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})


def agent_artifact_view_spec(artifact: ArtifactLike) -> ArtifactViewSpec:
    """Return the terminal-viewer spec for an agent artifact."""

    spec = ArtifactViewSpec(artifact.path, getattr(artifact, "kind", None))
    if str(spec.kind or "").lower() != "pdf":
        return spec

    source_path = _existing_markdown_source_path(
        getattr(artifact, "source_path", None),
        workspace_dir=getattr(artifact, "workspace_dir", None),
    )
    if source_path is None:
        return spec
    return ArtifactViewSpec(source_path, "markdown")


def _existing_markdown_source_path(
    source_path: object,
    *,
    workspace_dir: object = None,
) -> Path | None:
    if not isinstance(source_path, str) or not source_path:
        return None

    path = Path(source_path).expanduser()
    candidates: list[Path] = []
    if not path.is_absolute() and isinstance(workspace_dir, str) and workspace_dir:
        candidates.append(Path(workspace_dir).expanduser() / path)
    candidates.append(path)

    for candidate in candidates:
        if candidate.suffix.lower() not in _MARKDOWN_SOURCE_SUFFIXES:
            continue
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None

"""ACE artifact-file provider helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.artifact_file_facade import ArtifactFile, list_artifact_files

from ...models.agent import Agent


@dataclass(frozen=True)
class _ArtifactFilePage:
    artifact_files: list[ArtifactFile] = field(default_factory=list)
    request: object | None = None
    shared_snapshot: object | None = None


@dataclass(frozen=True)
class _ArtifactFileReadResult:
    value: _ArtifactFilePage
    used_daemon: bool = False


def read_artifact_files_for_tui(
    agent: Agent,
    *,
    selection_generation: object | None = None,
    args: Any | None = None,
    client: Any | None = None,
) -> _ArtifactFileReadResult:
    """Return selected-agent artifact files from direct source stores."""
    _ = (selection_generation, args, client)
    artifacts_dir = agent.get_artifacts_dir()
    artifact_files = [] if artifacts_dir is None else list_artifact_files(artifacts_dir)
    return _ArtifactFileReadResult(
        value=_ArtifactFilePage(artifact_files=artifact_files)
    )

"""Shared helpers for artifact-file modal tests."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.keymaps import load_keymap_registry
from sase.core.artifact_file_types import ArtifactFile


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self._keymap_registry = load_keymap_registry({})

    def compose(self) -> ComposeResult:
        yield from ()


def _artifact(
    index: int,
    *,
    label: str | None = None,
    path: str | None = None,
    kind: str = "markdown",
    source_path: str | None = None,
    workspace_dir: str | None = None,
    agent_artifacts_dir: str | None = None,
    project: str | None = "sase",
    sha256: str | None = None,
    size_bytes: int | None = None,
    mime_type: str | None = None,
) -> ArtifactFile:
    return ArtifactFile(
        id=f"default:{index:024x}",
        label=label or f"Artifact {index}",
        kind=kind,  # type: ignore[arg-type]
        path=path or f"/tmp/artifact-{index}.md",
        source_path=source_path,
        workspace_dir=workspace_dir,
        agent_artifacts_dir=agent_artifacts_dir,
        project=project,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type,
    )

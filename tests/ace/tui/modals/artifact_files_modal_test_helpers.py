"""Shared helpers for artifact-file modal tests."""

from __future__ import annotations

from types import SimpleNamespace

from textual.app import App, ComposeResult


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

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
) -> SimpleNamespace:
    return SimpleNamespace(
        label=label or f"Artifact {index}",
        kind=kind,
        path=path or f"/tmp/artifact-{index}.md",
        source_path=source_path,
        workspace_dir=workspace_dir,
        agent_artifacts_dir=agent_artifacts_dir,
    )

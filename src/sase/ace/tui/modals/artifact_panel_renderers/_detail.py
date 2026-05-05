"""Public artifact detail renderer dispatch."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Group, RenderableType
from rich.text import Text

from sase.ace.tui.graphics import GraphicsCapability
from sase.core.artifact_wire import (
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_DIRECTORY,
    ARTIFACT_KIND_FILE,
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_ROOT,
    ARTIFACT_KIND_THOUGHT,
    ArtifactDetailWire,
)

from ._common import FILE_PREVIEW_LINE_LIMIT, render_header
from ._files import render_directory, render_file
from ._kinds import (
    render_agent,
    render_bead,
    render_changespec,
    render_commit,
    render_project,
    render_root,
    render_thought,
    render_unknown,
)
from ._summaries import (
    render_diagnostics,
    render_link_summary,
    render_payload_summary,
)

ArtifactRenderer = Callable[..., RenderableType]

_RENDERERS: dict[str, ArtifactRenderer] = {
    ARTIFACT_KIND_ROOT: render_root,
    ARTIFACT_KIND_FILE: render_file,
    ARTIFACT_KIND_DIRECTORY: render_directory,
    ARTIFACT_KIND_PROJECT: render_project,
    ARTIFACT_KIND_CHANGESPEC: render_changespec,
    ARTIFACT_KIND_COMMIT: render_commit,
    ARTIFACT_KIND_BEAD: render_bead,
    ARTIFACT_KIND_AGENT: render_agent,
    ARTIFACT_KIND_THOUGHT: render_thought,
}


def render_artifact_detail(
    detail: ArtifactDetailWire,
    *,
    graphics_capability: GraphicsCapability | None = None,
    max_file_preview_lines: int = FILE_PREVIEW_LINE_LIMIT,
    preview_size_func: Callable[[], tuple[int, int]] | None = None,
) -> RenderableType:
    """Return a Rich renderable for the artifact detail pane."""
    node = detail.node
    if node is None:
        return Text("Artifact not found", style="dim italic")

    capability = graphics_capability or GraphicsCapability.unavailable(
        "terminal graphics unavailable in this artifact detail context"
    )
    sections: list[RenderableType] = [render_header(detail)]

    renderer = _RENDERERS.get(node.kind, render_unknown)
    sections.append(
        renderer(
            detail,
            capability,
            max_file_preview_lines=max_file_preview_lines,
            preview_size_func=preview_size_func,
        )
    )

    payloads = render_payload_summary(detail.payloads)
    if payloads is not None:
        sections.append(payloads)

    links = render_link_summary(detail)
    if links is not None:
        sections.append(links)

    diagnostics = render_diagnostics(detail)
    if diagnostics is not None:
        sections.append(diagnostics)

    return Group(*sections)

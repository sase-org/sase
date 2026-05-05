"""Tests for artifact panel detail renderers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.console import Console, RenderableType

from sase.ace.tui.graphics import GraphicsCapability
from sase.ace.tui.modals.artifact_panel_renderers import render_artifact_detail
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
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
)


def _render_text(renderable: RenderableType) -> str:
    console = Console(record=True, width=140, color_system=None)
    console.print(renderable)
    return console.export_text()


def _node(
    artifact_id: str,
    kind: str,
    *,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    search_text: str = "",
) -> ArtifactNodeWire:
    return ArtifactNodeWire(
        id=artifact_id,
        kind=kind,
        display_title=title or artifact_id,
        provenance="derived",
        search_text=search_text,
        metadata=metadata or {},
    )


def _detail(
    artifact_id: str,
    kind: str,
    *,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    payloads: list[ArtifactPayloadWire] | None = None,
    children: list[ArtifactNodeWire] | None = None,
    outbound_links: list[ArtifactLinkWire] | None = None,
    inbound_links: list[ArtifactLinkWire] | None = None,
    search_text: str = "",
) -> ArtifactDetailWire:
    return ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=_node(
            artifact_id,
            kind,
            title=title,
            metadata=metadata,
            search_text=search_text,
        ),
        payloads=payloads or [],
        children=children or [],
        outbound_links=outbound_links or [],
        inbound_links=inbound_links or [],
    )


@pytest.mark.parametrize(
    ("kind", "metadata", "expected"),
    [
        (ARTIFACT_KIND_ROOT, {}, "Artifact root"),
        (
            ARTIFACT_KIND_DIRECTORY,
            {"path": "/tmp/missing-renderer-directory"},
            "Directory is missing on disk",
        ),
        (
            ARTIFACT_KIND_PROJECT,
            {"project_name": "sase", "project_file": "/tmp/sase.gp"},
            "Project Name: sase",
        ),
        (
            ARTIFACT_KIND_CHANGESPEC,
            {"name": "feature/test", "status": "WIP", "bead_id": "sase-1"},
            "ChangeSpec",
        ),
        (
            ARTIFACT_KIND_COMMIT,
            {"hash": "abcdef123", "author": "A. Dev", "message": "Add renderer"},
            "Commit",
        ),
        (
            ARTIFACT_KIND_BEAD,
            {"status": "in_progress", "parent_id": "sase-23.4"},
            "Status: in_progress",
        ),
        (
            ARTIFACT_KIND_AGENT,
            {"status": "DONE", "provider": "codex", "model": "gpt"},
            "Provider: codex",
        ),
        (
            ARTIFACT_KIND_THOUGHT,
            {"source": "codex", "ordinal": 2},
            "Source: codex",
        ),
    ],
)
def test_kind_renderers_handle_constructed_details(
    kind: str, metadata: dict[str, Any], expected: str
) -> None:
    payloads = (
        [
            ArtifactPayloadWire(
                artifact_id="thought-1",
                payload_type="thought",
                payload={"text": "compact reasoning note"},
            )
        ]
        if kind == ARTIFACT_KIND_THOUGHT
        else []
    )
    detail = _detail(
        f"{kind}-1",
        kind,
        metadata=metadata,
        payloads=payloads,
        children=[
            _node("agent-1", "agent"),
            _node("file-1", "file"),
            _node("bead-1", "bead"),
        ],
    )

    rendered = _render_text(render_artifact_detail(detail))

    assert "Artifact" in rendered
    assert f"Kind: {kind}" in rendered
    assert expected in rendered


def test_file_renderer_handles_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"

    rendered = _render_text(
        render_artifact_detail(
            _detail("missing", ARTIFACT_KIND_FILE, metadata={"path": str(missing)})
        )
    )

    assert "Path:" in rendered
    assert "File is missing on disk" in rendered


def test_file_renderer_handles_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")

    rendered = _render_text(
        render_artifact_detail(
            _detail("empty", ARTIFACT_KIND_FILE, metadata={"path": str(empty)})
        )
    )

    assert "File is empty" in rendered


def test_file_renderer_previews_text_with_line_limit(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text("one = 1\ntwo = 2\nthree = 3\n", encoding="utf-8")

    rendered = _render_text(
        render_artifact_detail(
            _detail("sample", ARTIFACT_KIND_FILE, metadata={"path": str(path)}),
            max_file_preview_lines=2,
        )
    )

    assert "Showing first 2 of 3 loaded lines" in rendered
    assert "one = 1" in rendered
    assert "two = 2" in rendered
    assert "three = 3" not in rendered


def test_file_renderer_detects_diffish_text(tmp_path: Path) -> None:
    path = tmp_path / "saved-output.txt"
    path.write_text(
        "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )

    rendered = _render_text(
        render_artifact_detail(
            _detail("diff", ARTIFACT_KIND_FILE, metadata={"path": str(path)})
        )
    )

    assert "diff --git" in rendered
    assert "@@ -1 +1 @@" in rendered


def test_file_renderer_uses_supported_image_fallback(tmp_path: Path) -> None:
    image = tmp_path / "preview.png"
    image.write_bytes(b"not actually decoded when graphics are unavailable")

    rendered = _render_text(
        render_artifact_detail(
            _detail("image", ARTIFACT_KIND_FILE, metadata={"path": str(image)}),
            graphics_capability=GraphicsCapability.unavailable("test fallback"),
            preview_size_func=lambda: (12, 4),
        )
    )

    assert "Image preview unavailable" in rendered
    assert "test fallback" in rendered


def test_bead_renderer_includes_worker_link() -> None:
    detail = _detail(
        "sase-23.4.3",
        ARTIFACT_KIND_BEAD,
        metadata={"status": "in_progress"},
        outbound_links=[
            ArtifactLinkWire(
                id="worker",
                link_type="worker",
                source_id="sase-23.4.3",
                target_id="agent-1",
            )
        ],
    )

    rendered = _render_text(render_artifact_detail(detail))

    assert "Worker links: agent-1" in rendered


def test_agent_renderer_lists_payload_types_and_related_artifacts() -> None:
    detail = _detail(
        "agent-1",
        ARTIFACT_KIND_AGENT,
        metadata={"status": "DONE", "provider": "codex", "workspace_path": "/tmp/ws"},
        payloads=[
            ArtifactPayloadWire(artifact_id="agent-1", payload_type="transcript"),
            ArtifactPayloadWire(artifact_id="agent-1", payload_type="diff"),
        ],
        children=[
            _node("thought-1", "thought"),
            _node("sase-1", "bead"),
            _node("cl-1", "changespec"),
        ],
    )

    rendered = _render_text(render_artifact_detail(detail))

    assert "Artifact payloads: diff, transcript" in rendered
    assert "Linked thoughts: thought-1" in rendered
    assert "Linked changespecs: cl-1" in rendered


def test_renderer_handles_absent_payloads_and_metadata_gracefully() -> None:
    rendered = _render_text(
        render_artifact_detail(_detail("unknown-1", "unrecognized-kind"))
    )

    assert "No kind-specific metadata available" in rendered

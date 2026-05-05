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
        metadata={
            "status": "DONE",
            "provider": "codex",
            "workspace_path": "/tmp/ws",
            "retry_of": "agent-parent",
            "retried_as": "agent-retry",
            "follow_up_of": "agent-planner",
        },
        payloads=[
            ArtifactPayloadWire(artifact_id="agent-1", payload_type="transcript"),
            ArtifactPayloadWire(artifact_id="agent-1", payload_type="diff"),
        ],
        children=[
            _node("agent-retry", "agent"),
            _node("thought-1", "thought"),
            _node("sase-1", "bead"),
            _node("cl-1", "changespec"),
            _node("plan.md", "file", metadata={"artifact_type": "plan"}),
            _node("answer.md", "file", metadata={"payload_type": "question"}),
            _node("chat.md", "file", metadata={"role": "transcript"}),
            _node("saved.diff", "file", metadata={"role": "diff"}),
        ],
        outbound_links=[
            ArtifactLinkWire(
                id="created-1",
                link_type="created",
                source_id="agent-1",
                target_id="created-file",
            )
        ],
    )

    rendered = _render_text(render_artifact_detail(detail))

    assert "Retry Of: agent-parent" in rendered
    assert "Retried As: agent-retry" in rendered
    assert "Follow Up Of: agent-planner" in rendered
    assert "Artifact payloads: diff, transcript" in rendered
    assert "Created artifacts: created-file" in rendered
    assert "Linked agents: agent-retry" in rendered
    assert "Linked transcripts: chat.md" in rendered
    assert "Linked diffs: saved.diff" in rendered
    assert "Linked plans: plan.md" in rendered
    assert "Linked questions: answer.md" in rendered
    assert "Linked thoughts: thought-1" in rendered
    assert "Linked changespecs: cl-1" in rendered


def test_changespec_renderer_surfaces_artifact_panel_workflow_links() -> None:
    detail = _detail(
        "cs-1",
        ARTIFACT_KIND_CHANGESPEC,
        metadata={"name": "feature/test", "status": "WIP"},
        children=[
            _node("agent-1", "agent"),
            _node("commit-1", "commit"),
            _node("sase-1", "bead"),
            _node("plan.md", "file", metadata={"artifact_type": "plan"}),
            _node("question.json", "file", metadata={"role": "question"}),
            _node("transcript.md", "file", metadata={"role": "transcript"}),
            _node("diff.patch", "file", metadata={"role": "diff"}),
            _node("created.py", "file"),
        ],
    )

    rendered = _render_text(render_artifact_detail(detail))

    assert "Linked agents: agent-1" in rendered
    assert "Linked commits: commit-1" in rendered
    assert "Linked plans: plan.md" in rendered
    assert "Linked questions: question.json" in rendered
    assert "Linked transcripts: transcript.md" in rendered
    assert "Linked diffs: diff.patch" in rendered
    assert "Linked beads: sase-1" in rendered
    assert (
        "Linked files: plan.md, question.json, transcript.md, diff.patch, created.py"
        in rendered
    )
    assert "Legacy run log" not in rendered


def test_thought_renderer_surfaces_timeline_metadata_and_text() -> None:
    detail = _detail(
        "thought:abc123",
        ARTIFACT_KIND_THOUGHT,
        metadata={
            "source": "codex",
            "timestamp": "2026-05-05T16:12:00Z",
            "ordinal": 7,
            "agent_id": "agent-1",
        },
        payloads=[
            ArtifactPayloadWire(
                artifact_id="thought:abc123",
                payload_type="thought",
                payload={"text": "first line\nsecond line"},
            )
        ],
    )

    rendered = _render_text(render_artifact_detail(detail))

    assert "Source: codex" in rendered
    assert "Timestamp: 2026-05-05T16:12:00Z" in rendered
    assert "Ordinal: 7" in rendered
    assert "Agent Id: agent-1" in rendered
    assert "first line" in rendered
    assert "second line" in rendered


def test_renderer_handles_absent_payloads_and_metadata_gracefully() -> None:
    rendered = _render_text(
        render_artifact_detail(_detail("unknown-1", "unrecognized-kind"))
    )

    assert "No kind-specific metadata available" in rendered

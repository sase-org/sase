"""Tests for artifact panel detail renderers."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console, RenderableType

from sase.ace.tui.graphics import GraphicsCapability
from sase.ace.tui.modals.artifact_panel_state import (
    ArtifactDetailRenderContext,
    ArtifactRelationshipContext,
)
from sase.ace.tui.modals.artifact_panel_renderers import render_artifact_detail
from sase.core.artifact_wire import (
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_DIFF,
    ARTIFACT_FILE_TYPE_METADATA_KEY,
    ARTIFACT_FILE_TYPE_MISC,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_FILE_TYPE_PROJECT,
    ARTIFACT_FILE_TYPE_PROMPT,
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
    ArtifactTypeCountWire,
)


def _render_text(renderable: RenderableType) -> str:
    console = Console(
        file=io.StringIO(),
        record=True,
        width=140,
        color_system=None,
    )
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


def test_renderer_includes_relationship_context_strip_from_paged_totals() -> None:
    detail = _detail(
        "changespec:alpha",
        ARTIFACT_KIND_CHANGESPEC,
        title="Alpha CL",
    )
    context = ArtifactDetailRenderContext(
        parent_label="Project (project:sase)",
        children_loaded_count=2,
        children_total_count=12,
        child_labels=("Agent one (agent:one)", "Agent two (agent:two)"),
        outbound=(
            ArtifactRelationshipContext(
                "created",
                loaded_count=1,
                total_count=5,
                peer_labels=("Plan file (file:plan)",),
            ),
            ArtifactRelationshipContext(
                "related",
                loaded_count=1,
                total_count=1,
                peer_labels=("Related CL (changespec:related)",),
            ),
            ArtifactRelationshipContext(
                "worker",
                loaded_count=1,
                total_count=1,
                peer_labels=("Worker agent (agent:worker)",),
            ),
        ),
        inbound=(
            ArtifactRelationshipContext(
                "created",
                loaded_count=1,
                total_count=1,
                peer_labels=("Planner (agent:planner)",),
            ),
            ArtifactRelationshipContext(
                "related",
                loaded_count=2,
                total_count=8,
                peer_labels=("Inbound CL (changespec:inbound)",),
            ),
        ),
        type_counts=(ArtifactTypeCountWire("agent", 12),),
    )

    rendered = _render_text(render_artifact_detail(detail, render_context=context))

    assert "Context" in rendered
    assert "Parent: Project (project:sase)" in rendered
    assert "Children: 2/12 - Agent one (agent:one), Agent two (agent:two)" in rendered
    assert "Created: 1/5 - Plan file (file:plan)" in rendered
    assert "Created by: 1 - Planner (agent:planner)" in rendered
    assert "Related: 1 - Related CL (changespec:related)" in rendered
    assert "Worker: 1 - Worker agent (agent:worker)" in rendered
    assert "Inbound: created=1, related=2/8" in rendered
    assert "Types: agent=12" in rendered


def test_renderer_avoids_duplicate_graph_links_when_context_has_relationships() -> None:
    detail = _detail(
        "changespec:alpha",
        ARTIFACT_KIND_CHANGESPEC,
        title="Alpha CL",
        children=[_node("agent:child", "agent", title="Child agent")],
        outbound_links=[
            ArtifactLinkWire(
                id="created-1",
                link_type="created",
                source_id="changespec:alpha",
                target_id="file:plan",
            )
        ],
        inbound_links=[
            ArtifactLinkWire(
                id="related-1",
                link_type="related",
                source_id="changespec:beta",
                target_id="changespec:alpha",
            )
        ],
    )
    context = ArtifactDetailRenderContext(
        parent_label="Project (project:sase)",
        children_loaded_count=1,
        children_total_count=1,
        outbound=(
            ArtifactRelationshipContext(
                "created",
                loaded_count=1,
                total_count=1,
            ),
        ),
        inbound=(
            ArtifactRelationshipContext(
                "related",
                loaded_count=1,
                total_count=1,
            ),
        ),
    )

    rendered = _render_text(render_artifact_detail(detail, render_context=context))

    assert "Context" in rendered
    assert "Children: 1" in rendered
    assert "Outbound: created=1" in rendered
    assert "Inbound: related=1" in rendered
    assert "Graph links" not in rendered


def test_renderer_keeps_graph_links_without_relationship_context() -> None:
    detail = _detail(
        "changespec:alpha",
        ARTIFACT_KIND_CHANGESPEC,
        children=[_node("agent:child", "agent", title="Child agent")],
        outbound_links=[
            ArtifactLinkWire(
                id="created-1",
                link_type="created",
                source_id="changespec:alpha",
                target_id="file:plan",
            )
        ],
    )
    context = ArtifactDetailRenderContext(
        type_counts=(ArtifactTypeCountWire("agent", 1),)
    )

    rendered = _render_text(render_artifact_detail(detail, render_context=context))

    assert "Context" in rendered
    assert "Types: agent=1" in rendered
    assert "Graph links" in rendered
    assert "Outbound: created=1" in rendered


@pytest.mark.parametrize(
    ("file_type", "filename", "content", "metadata", "expected"),
    [
        (
            ARTIFACT_FILE_TYPE_PLAN,
            "plan.md",
            "# Plan\n\nImplement renderer taxonomy.\n",
            {"source_agent": "planner-1", "bead_id": "sase-24.5.1"},
            ("Plan file", "Source Agent: planner-1", "Bead Id: sase-24.5.1"),
        ),
        (
            ARTIFACT_FILE_TYPE_DIFF,
            "changes.diff",
            "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
            {"changespec": "feature/renderers"},
            ("Diff file", "Diff stats: files=1, +1, -1", "Changespec"),
        ),
        (
            ARTIFACT_FILE_TYPE_CHAT,
            "response.md",
            "User: hello\nAssistant: hi\n",
            {"conversation_id": "conv-1", "provider": "codex"},
            ("Chat file", "Conversation Id: conv-1", "Provider: codex"),
        ),
        (
            ARTIFACT_FILE_TYPE_PROJECT,
            "project.gp",
            "NAME\nsample\n",
            {"project_name": "sample", "changespec_count": 2},
            ("Project file", "Project Name: sample", "Changespec Count: 2"),
        ),
        (
            ARTIFACT_FILE_TYPE_PROMPT,
            "raw_xprompt.md",
            "Run the workflow.\n",
            {"xprompt_tag": "bd/work_phase_bead", "workflow": "phase"},
            ("Prompt file", "Xprompt Tag: bd/work_phase_bead", "Workflow: phase"),
        ),
        (
            ARTIFACT_FILE_TYPE_MISC,
            "notes.txt",
            "loose note\n",
            {"description": "scratch file"},
            ("File", "Description: scratch file", "loose note"),
        ),
    ],
)
def test_file_renderer_uses_canonical_file_type_sections(
    tmp_path: Path,
    file_type: str,
    filename: str,
    content: str,
    metadata: dict[str, Any],
    expected: tuple[str, str, str],
) -> None:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    rendered = _render_text(
        render_artifact_detail(
            _detail(
                filename,
                ARTIFACT_KIND_FILE,
                metadata={
                    "path": str(path),
                    ARTIFACT_FILE_TYPE_METADATA_KEY: file_type,
                    **metadata,
                },
            )
        )
    )

    assert f"File type: {file_type}" in rendered
    for expected_text in expected:
        assert expected_text in rendered


def test_file_renderer_defaults_missing_file_type_to_misc(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_text("legacy file\n", encoding="utf-8")

    rendered = _render_text(
        render_artifact_detail(
            _detail("legacy", ARTIFACT_KIND_FILE, metadata={"path": str(path)})
        )
    )

    assert "File type: misc" in rendered
    assert "legacy file" in rendered


def test_file_renderer_surfaces_unknown_future_file_type(tmp_path: Path) -> None:
    path = tmp_path / "notebook.ipynb"
    path.write_text("{}", encoding="utf-8")

    rendered = _render_text(
        render_artifact_detail(
            _detail(
                "notebook",
                ARTIFACT_KIND_FILE,
                metadata={
                    "path": str(path),
                    ARTIFACT_FILE_TYPE_METADATA_KEY: "notebook",
                },
            )
        )
    )

    assert "File type: misc" in rendered
    assert "Unknown file type: notebook" in rendered
    assert "{}" in rendered


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

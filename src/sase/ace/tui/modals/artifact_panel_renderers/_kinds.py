"""Non-filesystem artifact kind renderers."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import RenderableType
from rich.text import Text

from sase.ace.tui.graphics import GraphicsCapability
from sase.core.artifact_wire import ArtifactDetailWire

from ._common import (
    append_artifact_groups,
    append_child_summary,
    append_created_artifacts,
    append_kv,
    append_linked_kinds,
    append_metadata_mapping,
    append_payload_types,
    append_selected_metadata,
    first_payload_value,
    payload_text,
    peer_ids_for_link_type,
    require_node,
    with_empty_notice,
)


def render_project(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("Project\n", style="bold")
    append_selected_metadata(
        text,
        node.metadata,
        (
            "project",
            "project_name",
            "project_file",
            "root",
            "workspace_root",
            "changespec_count",
        ),
    )
    append_child_summary(text, detail.children)
    return with_empty_notice(text)


def render_changespec(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("ChangeSpec\n", style="bold")
    append_selected_metadata(
        text,
        node.metadata,
        (
            "name",
            "status",
            "parent",
            "project_file",
            "cl",
            "pr",
            "plan_path",
            "question_path",
            "bug_id",
            "bead_id",
        ),
    )
    append_artifact_groups(
        text,
        detail,
        (
            ("agents", ("agent",)),
            ("commits", ("commit",)),
            ("plans", ("plan",)),
            ("questions", ("question", "hitl_question")),
            ("transcripts", ("transcript", "chat", "conversation")),
            ("diffs", ("diff", "patch", "delta")),
            ("beads", ("bead",)),
            ("files", ("file",)),
        ),
    )
    return with_empty_notice(text)


def render_commit(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("Commit\n", style="bold")
    append_selected_metadata(
        text,
        node.metadata,
        (
            "hash",
            "sha",
            "short_hash",
            "author",
            "date",
            "message",
            "changespec",
            "source_location",
        ),
    )
    append_linked_kinds(text, detail, ("file", "changespec", "agent", "bead"))
    return with_empty_notice(text)


def render_bead(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("Bead\n", style="bold")
    append_selected_metadata(
        text,
        node.metadata,
        (
            "id",
            "status",
            "issue_type",
            "tier",
            "parent_id",
            "assignee",
            "owner",
            "design",
            "dependencies",
            "children",
        ),
    )
    worker_ids = peer_ids_for_link_type(detail, "worker")
    if worker_ids:
        append_kv(text, "Worker links", ", ".join(worker_ids))
    return with_empty_notice(text)


def render_agent(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("Agent\n", style="bold")
    append_selected_metadata(
        text,
        node.metadata,
        (
            "status",
            "provider",
            "model",
            "runtime",
            "workspace",
            "workspace_num",
            "workspace_path",
            "artifacts_dir",
            "changespec",
            "cl_name",
            "bead_id",
            "retry_of",
            "retried_as",
            "follow_up_of",
        ),
    )
    append_payload_types(text, detail.payloads)
    append_created_artifacts(text, detail)
    append_artifact_groups(
        text,
        detail,
        (
            ("agents", ("agent",)),
            ("transcripts", ("transcript", "chat", "conversation")),
            ("diffs", ("diff", "patch", "delta")),
            ("plans", ("plan",)),
            ("questions", ("question", "hitl_question")),
            ("thoughts", ("thought",)),
            ("changespecs", ("changespec", "cl")),
            ("beads", ("bead",)),
            ("files", ("file",)),
        ),
    )
    return with_empty_notice(text)


def render_thought(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    payload = first_payload_value(detail.payloads, ("text", "thought", "content"))
    thought_text = payload_text(payload) or node.search_text

    text = Text()
    text.append("Thought\n", style="bold")
    append_selected_metadata(
        text,
        node.metadata,
        ("source", "timestamp", "ordinal", "index", "title", "agent_id"),
    )
    if thought_text:
        text.append("\n")
        text.append("Text\n", style="bold")
        lines = thought_text.splitlines()
        preview = "\n".join(lines[:40])
        text.append(preview)
        if len(lines) > 40:
            text.append(f"\n... {len(lines) - 40} more lines", style="dim italic")
        text.append("\n")
    return with_empty_notice(text)


def render_root(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    text = Text()
    text.append("Artifact root\n", style="bold")
    append_child_summary(text, detail.children)
    return text


def render_unknown(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("Metadata\n", style="bold")
    append_metadata_mapping(text, node.metadata)
    return with_empty_notice(text)

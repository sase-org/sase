"""Kind-specific Rich renderers for the artifact panel modal."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from sase.ace.tui.graphics import (
    GraphicsCapability,
    image_preview,
    image_preview_size_for_viewport,
    is_supported_image_path,
)
from sase.ace.tui.util.lazy_syntax import lazy_renderable
from sase.ace.tui.widgets.file_panel._messages import _EXTENSION_TO_LEXER
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
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactPayloadWire,
)

FILE_PREVIEW_LINE_LIMIT = 120
FILE_PREVIEW_MAX_BYTES = 256_000


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
    sections: list[RenderableType] = [_render_header(detail)]

    renderer = _RENDERERS.get(node.kind, _render_unknown)
    sections.append(
        renderer(
            detail,
            capability,
            max_file_preview_lines=max_file_preview_lines,
            preview_size_func=preview_size_func,
        )
    )

    payloads = _render_payload_summary(detail.payloads)
    if payloads is not None:
        sections.append(payloads)

    links = _render_link_summary(detail)
    if links is not None:
        sections.append(links)

    diagnostics = _render_diagnostics(detail)
    if diagnostics is not None:
        sections.append(diagnostics)

    return Group(*sections)


def _render_header(detail: ArtifactDetailWire) -> Text:
    node = detail.node
    assert node is not None
    text = Text()
    text.append("Artifact\n", style="bold")
    _append_kv(text, "ID", node.id)
    _append_kv(text, "Kind", node.kind)
    _append_kv(text, "Title", node.display_title)
    _append_kv(text, "Subtitle", node.subtitle)
    _append_kv(text, "Provenance", node.provenance)
    _append_kv(text, "Source", _join_compact([node.source_kind, node.source_id]))
    _append_kv(text, "Created", node.created_at)
    _append_kv(text, "Updated", node.updated_at)
    text.append("\n")
    return text


def _render_file(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    node = _require_node(detail)
    path = _path_from_node(node)
    text = Text()
    text.append("File\n", style="bold")
    _append_kv(text, "Path", path)
    _append_kv(text, "Size", _metadata_value(node.metadata, "size", "bytes"))
    _append_kv(text, "MTime", _metadata_value(node.metadata, "mtime", "modified_at"))

    if path is None:
        text.append("No file path metadata is available.\n", style="dim italic")
        return text

    expanded = Path(os.path.expanduser(path))
    if is_supported_image_path(expanded):
        columns, rows = (
            preview_size_func()
            if preview_size_func is not None
            else image_preview_size_for_viewport(reserved_rows=4)
        )
        return Group(
            text,
            image_preview(str(expanded), capability, columns=columns, rows=rows),
        )

    if not expanded.exists():
        text.append("File is missing on disk.\n", style="yellow")
        return text
    if not expanded.is_file():
        text.append("Path is not a regular file.\n", style="yellow")
        return text

    try:
        stat = expanded.stat()
        _append_kv(text, "Size", f"{stat.st_size:,} bytes")
        _append_kv(text, "MTime", str(int(stat.st_mtime)))
        content, byte_truncated = _read_text_preview(expanded)
    except OSError as exc:
        text.append(f"Could not read file: {exc}\n", style="yellow")
        return text

    if not content:
        text.append("File is empty.\n", style="dim italic")
        return text

    lines = content.splitlines()
    total_lines = len(lines)
    visible_lines = lines[:max_file_preview_lines]
    line_truncated = total_lines > max_file_preview_lines
    preview = "\n".join(visible_lines)
    lexer = _lexer_for_file(expanded, preview)

    notices = Text()
    if line_truncated:
        notices.append(
            f"Showing first {max_file_preview_lines} of {total_lines} loaded lines.\n",
            style="dim italic",
        )
    if byte_truncated:
        notices.append(
            f"Preview capped at {FILE_PREVIEW_MAX_BYTES:,} bytes.\n",
            style="dim italic",
        )

    return Group(
        text,
        notices,
        lazy_renderable(preview, lexer, line_numbers=True),
    )


def _render_directory(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("Directory\n", style="bold")
    path = _path_from_node(node)
    _append_kv(text, "Path", path)
    if path:
        expanded = Path(os.path.expanduser(path))
        if expanded.is_dir():
            try:
                entries = list(expanded.iterdir())
            except OSError as exc:
                text.append(f"Could not list directory: {exc}\n", style="yellow")
            else:
                file_count = sum(1 for entry in entries if entry.is_file())
                dir_count = sum(1 for entry in entries if entry.is_dir())
                _append_kv(text, "Filesystem entries", len(entries))
                _append_kv(text, "Directories", dir_count)
                _append_kv(text, "Files", file_count)
        elif expanded.exists():
            text.append("Path exists but is not a directory.\n", style="yellow")
        else:
            text.append("Directory is missing on disk.\n", style="yellow")
    _append_child_summary(text, detail.children)
    return text


def _render_project(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("Project\n", style="bold")
    _append_selected_metadata(
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
    _append_child_summary(text, detail.children)
    return _with_empty_notice(text)


def _render_changespec(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("ChangeSpec\n", style="bold")
    _append_selected_metadata(
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
    _append_artifact_groups(
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
    return _with_empty_notice(text)


def _render_commit(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("Commit\n", style="bold")
    _append_selected_metadata(
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
    _append_linked_kinds(text, detail, ("file", "changespec", "agent", "bead"))
    return _with_empty_notice(text)


def _render_bead(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("Bead\n", style="bold")
    _append_selected_metadata(
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
    worker_ids = _peer_ids_for_link_type(detail, "worker")
    if worker_ids:
        _append_kv(text, "Worker links", ", ".join(worker_ids))
    return _with_empty_notice(text)


def _render_agent(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("Agent\n", style="bold")
    _append_selected_metadata(
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
    _append_payload_types(text, detail.payloads)
    _append_created_artifacts(text, detail)
    _append_artifact_groups(
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
    return _with_empty_notice(text)


def _render_thought(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    payload = _first_payload_value(detail.payloads, ("text", "thought", "content"))
    thought_text = _payload_text(payload) or node.search_text

    text = Text()
    text.append("Thought\n", style="bold")
    _append_selected_metadata(
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
    return _with_empty_notice(text)


def _render_root(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    text = Text()
    text.append("Artifact root\n", style="bold")
    _append_child_summary(text, detail.children)
    return text


def _render_unknown(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = _require_node(detail)
    text = Text()
    text.append("Metadata\n", style="bold")
    _append_metadata_mapping(text, node.metadata)
    return _with_empty_notice(text)


_RENDERERS: dict[str, Callable[..., RenderableType]] = {
    ARTIFACT_KIND_ROOT: _render_root,
    ARTIFACT_KIND_FILE: _render_file,
    ARTIFACT_KIND_DIRECTORY: _render_directory,
    ARTIFACT_KIND_PROJECT: _render_project,
    ARTIFACT_KIND_CHANGESPEC: _render_changespec,
    ARTIFACT_KIND_COMMIT: _render_commit,
    ARTIFACT_KIND_BEAD: _render_bead,
    ARTIFACT_KIND_AGENT: _render_agent,
    ARTIFACT_KIND_THOUGHT: _render_thought,
}


def _render_payload_summary(payloads: list[ArtifactPayloadWire]) -> Text | None:
    if not payloads:
        return None
    text = Text()
    text.append("\nPayloads\n", style="bold")
    counts = Counter(payload.payload_type for payload in payloads)
    for payload_type, count in sorted(counts.items()):
        text.append(f"- {payload_type}: {count}\n")
    return text


def _render_link_summary(detail: ArtifactDetailWire) -> Text | None:
    if not detail.outbound_links and not detail.inbound_links and not detail.children:
        return None
    text = Text()
    text.append("\nGraph links\n", style="bold")
    _append_kv(text, "Path to root", len(detail.path_to_root))
    _append_kv(
        text,
        "Children",
        _format_kind_counts(node.kind for node in detail.children),
    )
    _append_link_counts(text, "Outbound", detail.outbound_links)
    _append_link_counts(text, "Inbound", detail.inbound_links)
    return text


def _render_diagnostics(detail: ArtifactDetailWire) -> Text | None:
    if not detail.diagnostics:
        return None
    text = Text()
    text.append("\nDiagnostics\n", style="bold yellow")
    for issue in detail.diagnostics[:8]:
        text.append(f"- {issue.severity}: {issue.message}\n")
    if len(detail.diagnostics) > 8:
        text.append(f"... {len(detail.diagnostics) - 8} more diagnostics\n")
    return text


def _append_link_counts(text: Text, label: str, links: list[ArtifactLinkWire]) -> None:
    if not links:
        _append_kv(text, label, "0")
        return
    counts = Counter(link.link_type for link in links)
    _append_kv(
        text,
        label,
        ", ".join(
            f"{link_type}={count}" for link_type, count in sorted(counts.items())
        ),
    )


def _append_child_summary(text: Text, children: list[ArtifactNodeWire]) -> None:
    _append_kv(
        text,
        "Child artifacts",
        _format_kind_counts(node.kind for node in children),
    )


def _append_linked_kinds(
    text: Text, detail: ArtifactDetailWire, kinds: tuple[str, ...]
) -> None:
    ids_by_kind: dict[str, list[str]] = defaultdict(list)
    for node in detail.children:
        if node.kind in kinds:
            ids_by_kind[node.kind].append(node.id)
    for kind in kinds:
        ids = ids_by_kind.get(kind)
        if ids:
            _append_kv(text, f"Linked {kind}s", ", ".join(ids[:8]))


def _append_artifact_groups(
    text: Text,
    detail: ArtifactDetailWire,
    groups: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    grouped = _semantic_artifact_ids(detail)
    for label, aliases in groups:
        ids: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            for artifact_id in grouped.get(alias, []):
                if artifact_id in seen:
                    continue
                seen.add(artifact_id)
                ids.append(artifact_id)
        if ids:
            _append_kv(text, f"Linked {label}", ", ".join(ids[:8]))


def _append_created_artifacts(text: Text, detail: ArtifactDetailWire) -> None:
    created_ids: list[str] = []
    node_id = detail.node.id if detail.node is not None else None
    for link in detail.outbound_links:
        if link.link_type == "created" and link.source_id == node_id:
            created_ids.append(link.target_id)
    if created_ids:
        _append_kv(text, "Created artifacts", ", ".join(created_ids[:8]))


def _semantic_artifact_ids(detail: ArtifactDetailWire) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for child in detail.children:
        for key in _semantic_keys_for_node(child):
            grouped[key].append(child.id)
    return grouped


def _semantic_keys_for_node(node: ArtifactNodeWire) -> set[str]:
    keys = {_normalize_semantic_key(node.kind)}
    for metadata_key in (
        "artifact_type",
        "payload_type",
        "role",
        "type",
        "kind",
        "source_kind",
    ):
        value = node.metadata.get(metadata_key)
        if isinstance(value, str):
            keys.add(_normalize_semantic_key(value))

    searchable = " ".join(
        part
        for part in (node.id, node.display_title, node.subtitle, node.search_text)
        if part
    ).casefold()
    for marker, key in (
        ("plan", "plan"),
        ("question", "question"),
        ("hitl", "question"),
        ("transcript", "transcript"),
        ("conversation", "conversation"),
        ("chat", "chat"),
        ("diff", "diff"),
        ("patch", "patch"),
        ("delta", "delta"),
    ):
        if marker in searchable:
            keys.add(key)
    return keys


def _normalize_semantic_key(value: str) -> str:
    return value.casefold().replace("-", "_").replace(" ", "_")


def _append_payload_types(text: Text, payloads: list[ArtifactPayloadWire]) -> None:
    if payloads:
        _append_kv(
            text,
            "Artifact payloads",
            ", ".join(sorted({payload.payload_type for payload in payloads})),
        )


def _append_selected_metadata(
    text: Text, metadata: Mapping[str, Any], keys: Iterable[str]
) -> None:
    ordered_keys = tuple(keys)
    key_set = set(ordered_keys)
    for key in ordered_keys:
        _append_kv(text, _label_from_key(key), metadata.get(key))
    remaining = {key: value for key, value in metadata.items() if key not in key_set}
    if remaining:
        text.append("\nOther metadata\n", style="bold")
        _append_metadata_mapping(text, remaining)


def _append_metadata_mapping(text: Text, metadata: Mapping[str, Any]) -> None:
    for key in sorted(metadata):
        _append_kv(text, _label_from_key(key), metadata[key])


def _append_kv(text: Text, label: str, value: Any) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    text.append(f"{label}: ", style="bold")
    text.append(f"{_format_value(value)}\n")


def _with_empty_notice(text: Text) -> Text:
    if len(text.plain.splitlines()) <= 1:
        text.append("No kind-specific metadata available.\n", style="dim italic")
    return text


def _metadata_value(metadata: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value is not None and value != "":
            return value
    return None


def _path_from_node(node: ArtifactNodeWire) -> str | None:
    value = _metadata_value(node.metadata, "path", "file_path", "abs_path")
    if value is None and node.kind == ARTIFACT_KIND_FILE and os.path.isabs(node.id):
        value = node.id
    if value is None:
        return None
    return str(value)


def _read_text_preview(path: Path) -> tuple[str, bool]:
    with open(path, encoding="utf-8", errors="replace") as file:
        content = file.read(FILE_PREVIEW_MAX_BYTES + 1)
    if len(content) <= FILE_PREVIEW_MAX_BYTES:
        return content, False
    return content[:FILE_PREVIEW_MAX_BYTES], True


def _lexer_for_file(path: Path, content: str) -> str:
    if _looks_like_diff(content):
        return "diff"
    return _EXTENSION_TO_LEXER.get(path.suffix.lower(), "text")


def _looks_like_diff(content: str) -> bool:
    for line in content.splitlines()[:20]:
        if line.startswith(("diff --git ", "@@ ", "+++ ", "--- ")):
            return True
    return False


def _peer_ids_for_link_type(detail: ArtifactDetailWire, link_type: str) -> list[str]:
    node = detail.node
    if node is None:
        return []
    peers: list[str] = []
    for link in [*detail.outbound_links, *detail.inbound_links]:
        if link.link_type != link_type:
            continue
        if link.source_id == node.id:
            peers.append(link.target_id)
        elif link.target_id == node.id:
            peers.append(link.source_id)
    return peers


def _first_payload_value(
    payloads: list[ArtifactPayloadWire], preferred_keys: tuple[str, ...]
) -> Any:
    for payload in payloads:
        value = payload.payload
        if isinstance(value, Mapping):
            for key in preferred_keys:
                candidate = value.get(key)
                if candidate:
                    return candidate
        elif value:
            return value
    return None


def _payload_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _format_value(value)


def _format_kind_counts(kinds: Iterable[str]) -> str:
    counts = Counter(kinds)
    if not counts:
        return "0"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _label_from_key(key: str) -> str:
    return key.replace("_", " ").title()


def _join_compact(parts: Iterable[str | None]) -> str | None:
    values = [part for part in parts if part]
    return " / ".join(values) if values else None


def _require_node(detail: ArtifactDetailWire) -> ArtifactNodeWire:
    node = detail.node
    assert node is not None
    return node

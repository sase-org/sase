"""Filesystem artifact renderers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path

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
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_DIFF,
    ARTIFACT_FILE_TYPE_MISC,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_FILE_TYPE_PROJECT,
    ARTIFACT_FILE_TYPE_PROMPT,
    ArtifactDetailWire,
)

from ._common import (
    FILE_PREVIEW_MAX_BYTES,
    append_child_summary,
    append_kv,
    append_selected_metadata,
    effective_file_type,
    metadata_value,
    path_from_node,
    require_node,
)

_TYPE_TITLES = {
    ARTIFACT_FILE_TYPE_PLAN: "Plan file",
    ARTIFACT_FILE_TYPE_DIFF: "Diff file",
    ARTIFACT_FILE_TYPE_CHAT: "Chat file",
    ARTIFACT_FILE_TYPE_PROJECT: "Project file",
    ARTIFACT_FILE_TYPE_PROMPT: "Prompt file",
    ARTIFACT_FILE_TYPE_MISC: "File",
}


@dataclass(frozen=True)
class _DiffStats:
    files_changed: int
    insertions: int
    deletions: int


def render_file(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    node = require_node(detail)
    path = path_from_node(node)
    file_type, unknown_file_type = effective_file_type(node.metadata)
    text = Text()
    text.append(f"{_TYPE_TITLES[file_type]}\n", style="bold")
    append_kv(text, "File type", file_type)
    append_kv(text, "Unknown file type", unknown_file_type)
    append_kv(text, "Path", path)
    _append_type_metadata(text, detail, file_type)

    if path is None:
        text.append("No file path metadata is available.\n", style="dim italic")
        return text

    return _render_file_preview(
        text,
        path,
        file_type,
        capability,
        max_file_preview_lines=max_file_preview_lines,
        preview_size_func=preview_size_func,
    )


def _append_type_metadata(
    text: Text, detail: ArtifactDetailWire, file_type: str
) -> None:
    node = require_node(detail)
    metadata = _without_common_file_metadata(node.metadata)
    if file_type == ARTIFACT_FILE_TYPE_PLAN:
        append_selected_metadata(
            text,
            metadata,
            (
                "plan_path",
                "sdd_plan_path",
                "source_agent",
                "source_agent_id",
                "planner",
                "planner_agent",
                "agent_id",
                "bead_id",
                "changespec",
            ),
        )
    elif file_type == ARTIFACT_FILE_TYPE_DIFF:
        append_selected_metadata(
            text,
            metadata,
            (
                "diff_path",
                "commit_diff_path",
                "source_agent",
                "source_agent_id",
                "agent_id",
                "changespec",
                "commit",
                "base",
                "head",
                "files_changed",
                "insertions",
                "deletions",
            ),
        )
    elif file_type == ARTIFACT_FILE_TYPE_CHAT:
        append_selected_metadata(
            text,
            metadata,
            (
                "response_path",
                "chat_path",
                "live_reply_path",
                "question_response_path",
                "conversation_id",
                "session_id",
                "provider",
                "model",
                "agent_id",
                "role",
                "source",
            ),
        )
    elif file_type == ARTIFACT_FILE_TYPE_PROJECT:
        append_selected_metadata(
            text,
            metadata,
            (
                "project",
                "project_name",
                "project_file",
                "root",
                "workspace_root",
                "changespec_count",
                "agent_count",
            ),
        )
    elif file_type == ARTIFACT_FILE_TYPE_PROMPT:
        append_selected_metadata(
            text,
            metadata,
            (
                "sdd_prompt_path",
                "prompt_markdown",
                "raw_xprompt_path",
                "xprompt",
                "xprompt_tag",
                "source_agent",
                "source_agent_id",
                "agent_id",
                "workflow",
                "step",
            ),
        )
    else:
        append_selected_metadata(
            text,
            metadata,
            (
                "source",
                "source_agent",
                "source_agent_id",
                "agent_id",
                "role",
                "description",
            ),
        )


def _without_common_file_metadata(metadata: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in metadata.items()
        if key
        not in {
            "path",
            "file_path",
            "abs_path",
            "artifact_type",
            "size",
            "bytes",
            "mtime",
            "modified_at",
        }
    }


def _render_file_preview(
    text: Text,
    path: str,
    file_type: str,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
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
        append_kv(text, "Size", f"{stat.st_size:,} bytes")
        append_kv(text, "MTime", str(int(stat.st_mtime)))
        content, byte_truncated = _read_text_preview(expanded)
    except OSError as exc:
        text.append(f"Could not read file: {exc}\n", style="yellow")
        return text

    if not content:
        text.append("File is empty.\n", style="dim italic")
        return text

    if file_type == ARTIFACT_FILE_TYPE_DIFF:
        _append_diff_stats(text, _diff_stats(content))

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


def _append_diff_stats(text: Text, stats: _DiffStats) -> None:
    append_kv(
        text,
        "Diff stats",
        (f"files={stats.files_changed}, +{stats.insertions}, -{stats.deletions}"),
    )


def _diff_stats(content: str) -> _DiffStats:
    changed_paths: set[str] = set()
    insertions = 0
    deletions = 0
    for line in content.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                changed_paths.add(parts[2])
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1
    return _DiffStats(
        files_changed=len(changed_paths),
        insertions=insertions,
        deletions=deletions,
    )


def render_directory(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    del capability, max_file_preview_lines, preview_size_func
    node = require_node(detail)
    text = Text()
    text.append("Directory\n", style="bold")
    path = path_from_node(node)
    append_kv(text, "Path", path)
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
                append_kv(text, "Filesystem entries", len(entries))
                append_kv(text, "Directories", dir_count)
                append_kv(text, "Files", file_count)
        elif expanded.exists():
            text.append("Path exists but is not a directory.\n", style="yellow")
        else:
            text.append("Directory is missing on disk.\n", style="yellow")
    append_child_summary(text, detail.children)
    return text


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

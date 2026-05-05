"""Filesystem artifact renderers."""

from __future__ import annotations

import os
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
from sase.core.artifact_wire import ArtifactDetailWire

from ._common import (
    FILE_PREVIEW_MAX_BYTES,
    append_child_summary,
    append_kv,
    metadata_value,
    path_from_node,
    require_node,
)


def render_file(
    detail: ArtifactDetailWire,
    capability: GraphicsCapability,
    *,
    max_file_preview_lines: int,
    preview_size_func: Callable[[], tuple[int, int]] | None,
) -> RenderableType:
    node = require_node(detail)
    path = path_from_node(node)
    text = Text()
    text.append("File\n", style="bold")
    append_kv(text, "Path", path)
    append_kv(text, "Size", metadata_value(node.metadata, "size", "bytes"))
    append_kv(text, "MTime", metadata_value(node.metadata, "mtime", "modified_at"))

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
        append_kv(text, "Size", f"{stat.st_size:,} bytes")
        append_kv(text, "MTime", str(int(stat.st_mtime)))
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

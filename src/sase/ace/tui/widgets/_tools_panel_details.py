"""Expanded-detail rendering helpers for the tools timeline."""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.tools import ToolCallEntry

from ._tools_panel_time import format_timestamp
from ._tools_panel_types import ToolDetailLevel

_EXPANDED_GUTTER = "    │ "
_EXPANDED_WRAP_INDENT = "      "
_PREVIEW_KEYS = (
    "stdout_preview",
    "stderr_preview",
    "output_preview",
    "content_preview",
    "result_preview",
    "preview",
)
_INPUT_PRIMARY_KEYS = (
    "file_path",
    "path",
    "url",
    "query",
    "pattern",
    "command",
)
_INPUT_FIELD_ORDER = (
    "description",
    "timeout",
    "replace_all",
    "offset",
    "limit",
    "content_length",
    "old_string_length",
    "new_string_length",
    "edits_count",
    "subagent_type",
    "prompt_length",
    "input_keys",
    "raw",
)


def _value_to_display(value: Any, *, multiline: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_value_to_display(item) for item in value)
    if isinstance(value, dict):
        pieces = [f"{key}={_value_to_display(nested)}" for key, nested in value.items()]
        return ", ".join(piece for piece in pieces if piece)
    text = str(value)
    if multiline:
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").splitlines())


def _primary_target(entry: ToolCallEntry) -> tuple[str, str] | None:
    for key in _INPUT_PRIMARY_KEYS:
        value = entry.tool_input_summary.get(key)
        if isinstance(value, str) and value:
            return key, _value_to_display(value, multiline=True)
    return None


def _compact_target_is_truncated(entry: ToolCallEntry, full_value: str) -> bool:
    normalized = _value_to_display(full_value)
    if "\n" in full_value or "\r" in full_value:
        return True
    if len(normalized) > 88:
        return True
    return normalized != entry.compact_target


def _input_field_items(
    entry: ToolCallEntry, primary_key: str | None
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    keys: list[str] = []
    for key in _INPUT_FIELD_ORDER:
        if key in entry.tool_input_summary:
            keys.append(key)
            seen.add(key)
    for key in entry.tool_input_summary:
        if key not in seen:
            keys.append(str(key))
    items: list[tuple[str, str]] = []
    for key in keys:
        if key == primary_key:
            continue
        value = entry.tool_input_summary.get(key)
        rendered = _value_to_display(value)
        if rendered:
            items.append((key, rendered))
    return items


def _append_detail_line(text: Text, label: str, value: str, *, style: str = "") -> None:
    text.append(_EXPANDED_GUTTER, style="dim")
    text.append(f"{label} ", style="dim italic")
    text.append(value, style=style)
    text.append("\n")


def _append_multiline_detail(
    text: Text,
    label: str,
    value: str,
    *,
    style: str = "",
    max_lines: int = 6,
) -> None:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").splitlines() or [value]
    shown = lines[:max_lines]
    text.append(_EXPANDED_GUTTER, style="dim")
    text.append(f"{label}", style="dim italic")
    text.append("\n")
    for line in shown:
        text.append(_EXPANDED_WRAP_INDENT, style="dim")
        text.append(line, style=style)
        text.append("\n")
    remaining = len(lines) - len(shown)
    if remaining > 0:
        text.append(_EXPANDED_WRAP_INDENT, style="dim")
        text.append(f"... (+{remaining} more lines)", style="dim italic")
        text.append("\n")


def _append_input_fields(text: Text, items: list[tuple[str, str]]) -> None:
    if not items:
        return
    line = Text(_EXPANDED_GUTTER, style="dim")
    for idx, (key, value) in enumerate(items):
        rendered = f"{key} {value}"
        if idx and cell_len(line.plain) + cell_len(rendered) + 3 > 118:
            text.append(line)
            text.append("\n")
            line = Text(_EXPANDED_GUTTER, style="dim")
        elif idx:
            line.append(" · ", style="dim")
        line.append(f"{key} ", style="dim italic")
        line.append(value)
    text.append(line)
    text.append("\n")


def _response_scalar_parts(entry: ToolCallEntry) -> list[str]:
    summary = entry.tool_response_summary
    parts: list[str] = []
    exit_code = summary.get("exit_code")
    if isinstance(exit_code, int):
        parts.append(f"exit {exit_code}")
    success = summary.get("success")
    if isinstance(success, bool):
        parts.append("ok" if success else "failed")
    elif entry.status == "failure":
        parts.append("failed")
    interrupted = summary.get("interrupted")
    if interrupted is True or entry.status == "interrupted":
        parts.append("interrupted")
    return parts


def _preview_style(key: str) -> str:
    if key == "stderr_preview":
        return "#FF8787"
    return "dim"


def _preview_label(key: str) -> str:
    return key.removesuffix("_preview").replace("_", " ")


def _metadata_line(entry: ToolCallEntry) -> str:
    parts: list[str] = []
    if entry.completed_at:
        parts.append(f"completed {format_timestamp(entry.completed_at)}")
    runtime_source = "/".join(
        part for part in (entry.runtime, entry.source) if isinstance(part, str) and part
    )
    if runtime_source:
        parts.append(runtime_source)
    for label, value in (
        ("mode", entry.permission_mode),
        ("agent", entry.agent_type),
        ("cwd", entry.cwd),
        ("tool", entry.tool_use_id),
    ):
        if value:
            parts.append(f"{label} {value}")
    if entry.session_id:
        parts.append(f"session {entry.session_id[:12]}")
    if entry.source_path:
        source = entry.source_path
        if entry.line_number:
            source = f"{source}:{entry.line_number}"
        parts.append(source)
    return " · ".join(parts)


def append_expanded_block(
    output: Text,
    entry: ToolCallEntry,
    *,
    detail_level: ToolDetailLevel,
) -> None:
    primary = _primary_target(entry)
    primary_key: str | None = None
    if primary is not None:
        primary_key, full_target = primary
        if _compact_target_is_truncated(entry, full_target):
            _append_multiline_detail(
                output,
                primary_key.replace("_", " "),
                full_target,
                style="#D7D7AF",
            )

    _append_input_fields(output, _input_field_items(entry, primary_key))

    response_parts = _response_scalar_parts(entry)
    if response_parts:
        _append_detail_line(output, "response", " · ".join(response_parts), style="dim")
    for key in _PREVIEW_KEYS:
        value = entry.tool_response_summary.get(key)
        if isinstance(value, str) and value:
            _append_multiline_detail(
                output,
                _preview_label(key),
                value,
                style=_preview_style(key),
            )

    error = entry.error
    response_error = entry.tool_response_summary.get("error")
    if not error and isinstance(response_error, str):
        error = response_error
    if error:
        _append_multiline_detail(output, "error", error, style="bold red")

    if detail_level >= ToolDetailLevel.FULL:
        metadata = _metadata_line(entry)
        if metadata:
            _append_detail_line(output, "meta", metadata, style="dim")


def expanded_markdown_lines(
    entry: ToolCallEntry,
    *,
    detail_level: ToolDetailLevel,
) -> list[str]:
    lines: list[str] = []
    primary = _primary_target(entry)
    primary_key: str | None = None
    if primary is not None:
        primary_key, full_target = primary
        if _compact_target_is_truncated(entry, full_target):
            lines.append(f"  {primary_key.replace('_', ' ')}:")
            lines.extend(f"    {line}" for line in full_target.splitlines())

    for key, value in _input_field_items(entry, primary_key):
        lines.append(f"  {key}: {value}")

    response_parts = _response_scalar_parts(entry)
    if response_parts:
        lines.append(f"  response: {' · '.join(response_parts)}")
    for key in _PREVIEW_KEYS:
        preview_value = entry.tool_response_summary.get(key)
        if isinstance(preview_value, str) and preview_value:
            preview_lines = (
                preview_value.replace("\r\n", "\n").replace("\r", "\n").splitlines()
            )
            lines.append(f"  {_preview_label(key)}:")
            for preview_line in preview_lines[:6]:
                lines.append(f"    {preview_line}")
            remaining = len(preview_lines) - 6
            if remaining > 0:
                lines.append(f"    ... (+{remaining} more lines)")

    error = entry.error
    response_error = entry.tool_response_summary.get("error")
    if not error and isinstance(response_error, str):
        error = response_error
    if error:
        lines.append("  error:")
        lines.extend(
            f"    {line}"
            for line in error.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        )

    if detail_level >= ToolDetailLevel.FULL:
        metadata = _metadata_line(entry)
        if metadata:
            lines.append(f"  meta: {metadata}")
    return lines

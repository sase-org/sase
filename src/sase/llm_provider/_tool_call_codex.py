"""Codex tool-call artifact normalization."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._tool_call_common import (
    SCHEMA_VERSION,
    preview_text,
    string_or_none,
    summarize_tool_input,
)
from ._tool_call_io import append_jsonl, append_writer_diagnostic


def append_codex_tool_call_event(event: Mapping[str, Any]) -> None:
    """Best-effort append of a Codex function-call event to ``tool_calls.jsonl``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    try:
        record = _normalize_codex_tool_call_event(event)
        if record is None:
            return
        append_jsonl(Path(artifacts_dir) / "tool_calls.jsonl", record)
    except Exception as exc:
        append_writer_diagnostic(artifacts_dir, event, exc)


def _normalize_codex_tool_call_event(
    event: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert a Codex ``function_call`` item into SASE's tool-call schema."""
    if event.get("type") != "item.completed":
        return None

    item = event.get("item")
    if not isinstance(item, Mapping) or item.get("type") != "function_call":
        return None

    raw_tool_name = string_or_none(item.get("name"))
    tool_name = _codex_display_tool_name(raw_tool_name)
    tool_input = _normalize_codex_tool_input(
        raw_tool_name,
        _parse_codex_arguments(item.get("arguments")),
    )
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "runtime": "codex",
        "event": "FunctionCall",
        "status": "success",
        "tool_input_summary": summarize_tool_input(tool_name, tool_input),
        "tool_response_summary": {},
    }

    if tool_name:
        record["tool_name"] = tool_name

    for key in ("call_id", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            record["tool_use_id"] = preview_text(value)
            break

    return record


def _codex_display_tool_name(tool_name: str | None) -> str | None:
    if tool_name in {"shell", "container.exec"}:
        return "Bash"
    if tool_name == "read_file":
        return "Read"
    if tool_name == "write_file":
        return "Write"
    if tool_name in {"apply_patch", "apply_diff"}:
        return "Edit"
    return tool_name


def _parse_codex_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    if isinstance(arguments, Mapping):
        return dict(arguments)
    return {}


def _normalize_codex_tool_input(
    raw_tool_name: str | None,
    tool_input: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(tool_input)

    if raw_tool_name in {"shell", "container.exec"}:
        command = normalized.get("command")
        if isinstance(command, list):
            normalized["command"] = " ".join(str(part) for part in command)
        return normalized

    if raw_tool_name in {"read_file", "write_file", "apply_patch", "apply_diff"}:
        path = normalized.get("path")
        if isinstance(path, str) and path and "file_path" not in normalized:
            normalized["file_path"] = path

    return normalized


normalize_codex_tool_call_event = _normalize_codex_tool_call_event

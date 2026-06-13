"""Tool-call entry model and display helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ToolCallEntry:
    """One normalized tool-call artifact record, with TUI display helpers."""

    recorded_at: str
    runtime: str
    event: str
    status: str
    tool_name: str | None = None
    tool_use_id: str | None = None
    duration_ms: int | None = None
    tool_input_summary: Mapping[str, Any] = field(default_factory=dict)
    tool_response_summary: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    transcript_path: str | None = None
    cwd: str | None = None
    permission_mode: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None
    parent_tool_use_id: str | None = None
    error: str | None = None
    is_interrupt: bool = False
    source: str | None = None
    artifact_dir: str | None = None
    source_path: str | None = None
    line_number: int = 0
    _recorded_at_sort: datetime = field(
        default=datetime.max.replace(tzinfo=UTC), compare=False, repr=False
    )
    _file_order: int = field(default=0, compare=False, repr=False)

    @property
    def display_tool_name(self) -> str:
        """Return a stable label for unknown tools and subagent events."""
        if self.tool_name:
            return self.tool_name
        if self.event in {"SubagentStart", "SubagentStop"}:
            return self.event
        return self.event or "unknown"

    @property
    def compact_target(self) -> str:
        """Best-effort target summary for one-line timeline rows."""
        return _compact_tool_target(
            self.tool_name,
            self.tool_input_summary,
            self.tool_response_summary,
        )

    @property
    def detail(self) -> str:
        """Best-effort one-line detail derived from input/response summaries."""
        return _tool_call_detail(
            self.tool_name,
            self.tool_input_summary,
            self.tool_response_summary,
            error=self.error,
        )


def _compact_tool_target(
    tool_name: str | None,
    tool_input_summary: Mapping[str, Any],
    tool_response_summary: Mapping[str, Any],
) -> str:
    """Return a compact target string for common tools."""
    del tool_response_summary
    for key in ("file_path", "path", "url", "query", "pattern", "description"):
        value = tool_input_summary.get(key)
        if isinstance(value, str) and value:
            return _one_line(value, 96)

    command = tool_input_summary.get("command")
    if isinstance(command, str) and command:
        return _one_line(command, 96)

    subagent_type = tool_input_summary.get("subagent_type")
    if isinstance(subagent_type, str) and subagent_type:
        return subagent_type

    if tool_name:
        return ""
    input_keys = tool_input_summary.get("input_keys")
    if isinstance(input_keys, list) and input_keys:
        return ", ".join(str(key) for key in input_keys[:4])
    return ""


def _tool_call_detail(
    tool_name: str | None,
    tool_input_summary: Mapping[str, Any],
    tool_response_summary: Mapping[str, Any],
    *,
    error: str | None = None,
) -> str:
    """Return a bounded one-line detail string for a timeline row."""
    if error:
        return _one_line(error, 140)

    response_error = tool_response_summary.get("error")
    if isinstance(response_error, str) and response_error:
        return _one_line(response_error, 140)

    parts: list[str] = []
    if tool_name == "Bash":
        exit_code = tool_response_summary.get("exit_code")
        if isinstance(exit_code, int):
            parts.append(f"exit {exit_code}")
    for key in (
        "stdout_preview",
        "stderr_preview",
        "output_preview",
        "content_preview",
        "result_preview",
        "preview",
    ):
        value = tool_response_summary.get(key)
        if isinstance(value, str) and value:
            parts.append(_one_line(value, 120))
            break

    if not parts:
        for key in ("content_length", "old_string_length", "new_string_length"):
            value = tool_input_summary.get(key)
            if isinstance(value, int):
                parts.append(f"{key}={value}")
        edits = tool_input_summary.get("edits_count")
        if isinstance(edits, int):
            parts.append(f"edits={edits}")

    if not parts:
        keys = tool_response_summary.get("response_keys")
        if isinstance(keys, list) and keys:
            parts.append("response: " + ", ".join(str(key) for key in keys[:4]))

    return " | ".join(parts)


def _one_line(value: str, limit: int) -> str:
    text = " ".join(value.replace("\r\n", "\n").replace("\r", "\n").splitlines())
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[{len(text) - limit} more]"

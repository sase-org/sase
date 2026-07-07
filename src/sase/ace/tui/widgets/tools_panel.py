"""Agent tools panel widget for the ace TUI."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, cast

from rich.cells import cell_len
from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.tools import (
    SlowToolSource,
    ToolCallEntry,
    build_cached_slow_tool_sources,
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from sase.ace.tui.tools.cache import (
    ToolsCacheEntry,
    fetch_tool_calls_cached,
    get_cache_key,
    invalidate_cached_tool_calls,
    mark_tool_call_fetch_started,
    peek_tool_calls_cache_entry,
    should_throttle_tool_call_fetch,
    tools_cache,
)
from sase.ace.tui.tools.slow import format_long_duration
from sase.core.time import get_timezone

from ..util.trace import tui_trace
from .prompt_panel._agent_context_common import truncate_display

_ToolsCacheEntry = ToolsCacheEntry
_tools_cache = tools_cache

_CHIP_COLORS = (
    "#87D7FF",
    "#5FD75F",
    "#D7AF5F",
    "#AF87FF",
    "#5FD7D7",
    "#D787AF",
)
_SOURCE_CHIP_WIDTH = 7
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


class ToolDetailLevel(IntEnum):
    """Progressive disclosure levels for the tools timeline."""

    COMPACT = 0
    EXPANDED = 1
    FULL = 2


_DETAIL_LEVEL_LABELS: dict[ToolDetailLevel, str] = {
    ToolDetailLevel.COMPACT: "compact",
    ToolDetailLevel.EXPANDED: "expanded",
    ToolDetailLevel.FULL: "full",
}


@dataclass(frozen=True)
class _ToolTimelineRow:
    entry: ToolCallEntry
    source_label: str | None = None
    palette_index: int = 0


@dataclass(frozen=True)
class _ToolsPanelFetchResult:
    entries: tuple[ToolCallEntry, ...] | None
    rows: tuple[_ToolTimelineRow, ...] | None
    fetch_time: datetime


class ToolsVisibilityChanged(Message):
    """Message posted when tools panel availability changes."""

    def __init__(self, has_tools: bool) -> None:
        super().__init__()
        self.has_tools = has_tools


def _format_timestamp(iso_str: str) -> str:
    """Format an ISO timestamp to HH:MM:SS display."""
    try:
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        dt = dt.astimezone(get_timezone())
        return dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "??:??:??"


def _format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return ""
    if duration_ms >= SLOW_TOOL_CALL_THRESHOLD_MS:
        return format_long_duration(duration_ms)
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _status_label(status: str) -> str:
    return {
        "success": "ok",
        "failure": "fail",
        "interrupted": "stop",
        "subagent": "agent",
        "pending": "wait",
        "incomplete": "miss",
    }.get(status, status or "unknown")


def _status_style(status: str) -> str:
    return {
        "success": "bold green",
        "failure": "bold red",
        "interrupted": "bold yellow",
        "subagent": "bold #87D7FF",
        "pending": "bold #FFD787",
        "incomplete": "dim #FFD787",
    }.get(status, "dim")


def _append_bounded(
    text: Text, value: str, *, style: str = "", limit: int = 96
) -> None:
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1] + "..."
    text.append(value, style=style)


def _pad_cells(value: str, width: int) -> str:
    return value + (" " * max(0, width - cell_len(value)))


def _append_source_chip(
    text: Text,
    label: str,
    *,
    palette_index: int,
) -> None:
    chip = _pad_cells(truncate_display(label, _SOURCE_CHIP_WIDTH), _SOURCE_CHIP_WIDTH)
    text.append(
        chip,
        style=f"italic {_CHIP_COLORS[palette_index % len(_CHIP_COLORS)]}",
    )


def _coerce_detail_level(level: ToolDetailLevel | int) -> ToolDetailLevel:
    value = max(
        ToolDetailLevel.COMPACT,
        min(ToolDetailLevel.FULL, int(level)),
    )
    return ToolDetailLevel(value)


def _detail_level_label(level: ToolDetailLevel | int) -> str:
    return _DETAIL_LEVEL_LABELS[_coerce_detail_level(level)]


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
        parts.append(f"completed {_format_timestamp(entry.completed_at)}")
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


def _append_expanded_block(
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


def _expanded_markdown_lines(
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


def _rows_from_entries(
    entries: Sequence[ToolCallEntry] | None,
) -> tuple[_ToolTimelineRow, ...] | None:
    if entries is None:
        return None
    return tuple(_ToolTimelineRow(entry=entry) for entry in entries)


def _rows_from_sources(
    sources: tuple[SlowToolSource, ...] | None,
) -> tuple[_ToolTimelineRow, ...] | None:
    if sources is None:
        return None
    rows = tuple(
        _ToolTimelineRow(
            entry=entry,
            source_label=source.label,
            palette_index=source.palette_index,
        )
        for source in sources
        for entry in source.entries
    )
    return tuple(sorted(rows, key=_timeline_row_sort_key))


def _timeline_row_sort_key(row: _ToolTimelineRow) -> tuple[object, ...]:
    entry = row.entry
    return (
        entry._recorded_at_sort,
        entry._file_order,
        entry.line_number,
        entry.tool_use_id or "",
        row.palette_index,
    )


def _latest_cached_fetch_time(agent: Agent) -> datetime | None:
    fetch_times = [
        cache_entry.fetch_time
        for row in (agent, *tuple(getattr(agent, "runtime_children", ())))
        if row is agent or row.is_agent_entry
        for cache_entry in (peek_tool_calls_cache_entry(row),)
        if cache_entry is not None
    ]
    return max(fetch_times) if fetch_times else None


def _source_cache_agents(agent: Agent) -> tuple[Agent, ...]:
    return (
        agent,
        *tuple(
            child
            for child in getattr(agent, "runtime_children", ())
            if child.is_agent_entry
        ),
    )


def _should_throttle_tool_sources(agent: Agent) -> bool:
    return any(
        should_throttle_tool_call_fetch(row) for row in _source_cache_agents(agent)
    )


def _mark_tool_source_fetch_started(agent: Agent) -> None:
    for row in _source_cache_agents(agent):
        mark_tool_call_fetch_started(row)


def _invalidate_tool_source_caches(agent: Agent) -> None:
    for row in _source_cache_agents(agent):
        invalidate_cached_tool_calls(row)


def _build_tools_timeline_text(
    entries: Sequence[ToolCallEntry] | None,
    fetch_time: datetime,
    *,
    is_stale: bool = False,
    rows: Sequence[_ToolTimelineRow] | None = None,
    detail_level: ToolDetailLevel | int = ToolDetailLevel.COMPACT,
) -> Text:
    """Build the Rich Text timeline for tool-call entries."""
    detail_level = _coerce_detail_level(detail_level)
    if entries is None:
        return Text("No tools artifact available", style="dim italic")
    if not entries:
        return Text("No tool calls recorded", style="dim italic")

    failures = sum(1 for entry in entries if entry.status == "failure")
    interrupted = sum(1 for entry in entries if entry.status == "interrupted")
    output = Text()
    output.append("TOOLS", style="bold #87D7FF underline")
    if is_stale:
        output.append(" (refreshing...)", style="dim italic")
    output.append("\n")
    summary = (
        f"{len(entries)} calls · {failures} failures · {interrupted} interrupted "
        f"· refreshed {fetch_time.strftime('%H:%M:%S')}"
    )
    if detail_level >= ToolDetailLevel.EXPANDED:
        summary = f"{summary} · detail: {_detail_level_label(detail_level)}"
    output.append(f"{summary}\n\n", style="dim")

    timeline_rows = tuple(rows) if rows is not None else _rows_from_entries(entries)
    for row in timeline_rows or ():
        entry = row.entry
        output.append(_format_timestamp(entry.recorded_at), style="dim")
        output.append("  ")
        output.append(
            _status_label(entry.status).ljust(5), style=_status_style(entry.status)
        )
        output.append("  ")
        if row.source_label:
            _append_source_chip(
                output,
                row.source_label,
                palette_index=row.palette_index,
            )
            output.append("  ")
        _append_bounded(output, entry.display_tool_name, style="bold")

        target = entry.compact_target
        if target:
            output.append("  ")
            _append_bounded(output, target, style="#D7D7AF", limit=88)

        duration = _format_duration(entry.duration_ms)
        if duration:
            output.append("  ")
            style = (
                "bold #FFAF5F"
                if entry.duration_ms is not None
                and entry.duration_ms >= SLOW_TOOL_CALL_THRESHOLD_MS
                else "dim"
            )
            output.append(duration, style=style)

        detail = entry.detail
        if detail:
            output.append("\n    ")
            _append_bounded(output, detail, style="dim", limit=140)
        output.append("\n")
        if detail_level >= ToolDetailLevel.EXPANDED:
            _append_expanded_block(output, entry, detail_level=detail_level)
            output.append("\n")

    return output


def _build_tools_timeline_markdown(
    entries: Sequence[ToolCallEntry] | None,
    fetch_time: datetime,
    *,
    rows: Sequence[_ToolTimelineRow] | None = None,
    detail_level: ToolDetailLevel | int = ToolDetailLevel.COMPACT,
) -> str | None:
    """Build a plain markdown rendering for editor/export actions."""
    detail_level = _coerce_detail_level(detail_level)
    if entries is None:
        return "TOOLS\n\nNo tools artifact available.\n"
    if not entries:
        return "TOOLS\n\nNo tool calls recorded.\n"

    summary = f"{len(entries)} calls · refreshed {fetch_time.strftime('%H:%M:%S')}"
    if detail_level >= ToolDetailLevel.EXPANDED:
        summary = f"{summary} · detail: {_detail_level_label(detail_level)}"
    lines = [
        "TOOLS",
        "",
        summary,
        "",
    ]
    timeline_rows = tuple(rows) if rows is not None else _rows_from_entries(entries)
    for row in timeline_rows or ():
        entry = row.entry
        pieces = [
            _format_timestamp(entry.recorded_at),
            _status_label(entry.status),
        ]
        if row.source_label:
            pieces.append(row.source_label)
        pieces.append(entry.display_tool_name)
        if entry.compact_target:
            pieces.append(entry.compact_target)
        if _format_duration(entry.duration_ms):
            pieces.append(_format_duration(entry.duration_ms))
        lines.append(" | ".join(pieces))
        if entry.detail:
            lines.append(f"  {entry.detail}")
        if detail_level >= ToolDetailLevel.EXPANDED:
            lines.extend(_expanded_markdown_lines(entry, detail_level=detail_level))
            lines.append("")
    lines.append("")
    return "\n".join(lines)


class AgentToolsPanel(Static):
    """Panel showing normalized tool-call artifacts for the selected agent."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_worker: Worker[_ToolsPanelFetchResult] | None = None
        self._has_displayed_content: bool = False
        self._last_entries: tuple[ToolCallEntry, ...] | None = None
        self._last_rows: tuple[_ToolTimelineRow, ...] | None = None
        self._last_fetch_time: datetime | None = None
        self._is_background_refreshing: bool = False
        self._detail_level: ToolDetailLevel = ToolDetailLevel.COMPACT

    @property
    def detail_level(self) -> ToolDetailLevel:
        """Current timeline detail level."""
        return self._detail_level

    def expand_detail(self) -> bool:
        """Expand the tools timeline by one detail level."""
        return self.set_detail_level(self._detail_level + 1)

    def collapse_detail(self) -> bool:
        """Collapse the tools timeline by one detail level."""
        return self.set_detail_level(self._detail_level - 1)

    def set_detail_level(
        self,
        level: ToolDetailLevel | int,
        *,
        rerender: bool = True,
    ) -> bool:
        """Set the tools timeline detail level.

        Returns True when the level changed. When ``rerender`` is true, empty
        panels do not change level because the keypress should remain a no-op.
        """
        next_level = _coerce_detail_level(level)
        if next_level == self._detail_level:
            return False
        if rerender and not self._has_tool_rows():
            return False
        self._detail_level = next_level
        if rerender:
            self._rerender_cached_tools()
        return True

    def _has_tool_rows(self) -> bool:
        return bool(self._last_entries)

    def _rerender_cached_tools(self) -> None:
        if self._last_fetch_time is None:
            return
        scroll_pos = self._save_scroll_position()
        self._display_tools_with_timestamp(
            self._last_entries,
            self._last_fetch_time,
            post_visibility_message=False,
            is_stale=self._is_background_refreshing,
            rows=self._last_rows,
        )
        self._restore_scroll_position(scroll_pos)

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        """Update with agent tool-call records."""
        with tui_trace("widget.tools_panel.update_display"):
            self._update_display_impl(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )

    def _update_display_impl(
        self, agent: Agent, stale_threshold_seconds: int = 10
    ) -> None:
        del stale_threshold_seconds  # freshness now checked inside the worker
        self._current_agent = agent
        cached_result = self._cached_fetch_result(agent)

        if cached_result is not None:
            self._display_tools_result(
                cached_result,
                post_visibility_message=True,
            )
        else:
            self._show_loading()

        if _should_throttle_tool_sources(agent):
            return

        if self._current_worker is not None and self._current_worker.is_running:
            return

        _mark_tool_source_fetch_started(agent)

        def fetch_task() -> _ToolsPanelFetchResult:
            return self._fetch_tools_result_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def refresh_tools(self, agent: Agent) -> None:
        """Force refresh tool-call records for an agent."""
        self._current_agent = agent
        cached_result = self._cached_fetch_result(agent)

        if cached_result is not None:
            self._is_background_refreshing = True
            self._display_tools_result(
                cached_result,
                post_visibility_message=True,
                is_stale=True,
            )
            # Force a re-read by invalidating the mtime watermark.
            _invalidate_tool_source_caches(agent)
        else:
            self._show_loading()

        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        def fetch_task() -> _ToolsPanelFetchResult:
            return self._fetch_tools_result_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def get_tools_text(self) -> str | None:
        """Return a markdown/plain text timeline for editor actions."""
        if self._last_fetch_time is None:
            return None
        return _build_tools_timeline_markdown(
            self._last_entries,
            self._last_fetch_time,
            rows=self._last_rows,
            detail_level=self._detail_level,
        )

    def show_empty(self) -> None:
        """Show empty state."""
        self._has_displayed_content = False
        self._last_entries = None
        self._last_rows = None
        self._last_fetch_time = None
        self.update(Text("No agent selected", style="dim italic"))

    def _show_loading(self) -> None:
        """Display loading indicator only if panel was previously visible."""
        if not self._has_displayed_content:
            return
        self.update(Text("Loading tool calls...", style="bold #87D7FF"))

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.app.query_one("#agent-tools-scroll", VerticalScroll)
        except Exception:
            return None

    def _save_scroll_position(self) -> float:
        container = self._get_scroll_container()
        if container is not None:
            return container.scroll_y
        return 0.0

    def _restore_scroll_position(self, position: float) -> None:
        container = self._get_scroll_container()
        if container is not None:
            self.call_after_refresh(
                lambda: container.scroll_to(y=position, animate=False)
            )

    def _display_tools_with_timestamp(
        self,
        entries: tuple[ToolCallEntry, ...] | None,
        fetch_time: datetime,
        *,
        post_visibility_message: bool = True,
        is_stale: bool = False,
        rows: tuple[_ToolTimelineRow, ...] | None = None,
    ) -> None:
        self._last_entries = entries
        self._last_rows = rows
        self._last_fetch_time = fetch_time

        if post_visibility_message:
            self.post_message(ToolsVisibilityChanged(has_tools=bool(entries)))

        self.update(
            _build_tools_timeline_text(
                entries,
                fetch_time,
                is_stale=is_stale,
                rows=rows,
                detail_level=self._detail_level,
            )
        )
        self._has_displayed_content = True

    def _display_tools_result(
        self,
        result: _ToolsPanelFetchResult,
        *,
        post_visibility_message: bool = True,
        is_stale: bool = False,
    ) -> None:
        self._display_tools_with_timestamp(
            result.entries,
            result.fetch_time,
            post_visibility_message=post_visibility_message,
            is_stale=is_stale,
            rows=result.rows,
        )

    def _cached_fetch_result(self, agent: Agent) -> _ToolsPanelFetchResult | None:
        if supports_slow_tool_sources(agent):
            sources = build_cached_slow_tool_sources(agent)
            if sources is None:
                return None
            rows = _rows_from_sources(sources)
            fetch_time = _latest_cached_fetch_time(agent) or datetime.now()
            return _ToolsPanelFetchResult(
                entries=None if rows is None else tuple(row.entry for row in rows),
                rows=rows,
                fetch_time=fetch_time,
            )

        cache_entry = peek_tool_calls_cache_entry(agent)
        if cache_entry is None:
            return None
        return _ToolsPanelFetchResult(
            entries=cache_entry.entries,
            rows=_rows_from_entries(cache_entry.entries),
            fetch_time=cache_entry.fetch_time,
        )

    def _fetch_tools_result_in_background(self, agent: Agent) -> _ToolsPanelFetchResult:
        if supports_slow_tool_sources(agent):
            sources = build_slow_tool_sources(agent)
            rows = _rows_from_sources(sources)
            return _ToolsPanelFetchResult(
                entries=None if rows is None else tuple(row.entry for row in rows),
                rows=rows,
                fetch_time=_latest_cached_fetch_time(agent) or datetime.now(),
            )

        entries = self._fetch_tools_in_background(agent)
        cache_entry = peek_tool_calls_cache_entry(agent)
        return _ToolsPanelFetchResult(
            entries=entries,
            rows=_rows_from_entries(entries),
            fetch_time=(
                cache_entry.fetch_time if cache_entry is not None else datetime.now()
            ),
        )

    def _fetch_tools_in_background(
        self, agent: Agent
    ) -> tuple[ToolCallEntry, ...] | None:
        return fetch_tool_calls_cached(agent)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        if event.worker != self._current_worker:
            return

        self._is_background_refreshing = False

        if event.state == WorkerState.SUCCESS:
            result = cast(_ToolsPanelFetchResult, event.worker.result)
            scroll_pos = self._save_scroll_position()
            self._display_tools_result(
                result,
                post_visibility_message=result.entries != self._last_entries,
            )
            self._restore_scroll_position(scroll_pos)
        elif event.state == WorkerState.ERROR:
            text = Text()
            text.append("Error fetching tool calls\n", style="bold red")
            text.append("Failed to read tool-call artifacts.", style="dim")
            self.update(text)
        elif event.state == WorkerState.CANCELLED:
            pass


__all__ = [
    "AgentToolsPanel",
    "ToolDetailLevel",
    "ToolsVisibilityChanged",
    "_ToolsCacheEntry",
    "_build_tools_timeline_markdown",
    "_build_tools_timeline_text",
    "_tools_cache",
    "get_cache_key",
]

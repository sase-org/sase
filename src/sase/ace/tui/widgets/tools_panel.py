"""Agent tools panel widget for the ace TUI."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Sequence
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.tools import ToolCallEntry
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

_ToolsCacheEntry = ToolsCacheEntry
_tools_cache = tools_cache


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
    }.get(status, status or "unknown")


def _status_style(status: str) -> str:
    return {
        "success": "bold green",
        "failure": "bold red",
        "interrupted": "bold yellow",
        "subagent": "bold #87D7FF",
        "pending": "bold #FFD787",
    }.get(status, "dim")


def _append_bounded(
    text: Text, value: str, *, style: str = "", limit: int = 96
) -> None:
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1] + "..."
    text.append(value, style=style)


def _build_tools_timeline_text(
    entries: Sequence[ToolCallEntry] | None,
    fetch_time: datetime,
    *,
    is_stale: bool = False,
) -> Text:
    """Build the Rich Text timeline for tool-call entries."""
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
    output.append(
        f"{len(entries)} calls · {failures} failures · {interrupted} interrupted "
        f"· refreshed {fetch_time.strftime('%H:%M:%S')}\n\n",
        style="dim",
    )

    for entry in entries:
        output.append(_format_timestamp(entry.recorded_at), style="dim")
        output.append("  ")
        output.append(
            _status_label(entry.status).ljust(5), style=_status_style(entry.status)
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

    return output


def _build_tools_timeline_markdown(
    entries: Sequence[ToolCallEntry] | None,
    fetch_time: datetime,
) -> str | None:
    """Build a plain markdown rendering for editor/export actions."""
    if entries is None:
        return "TOOLS\n\nNo tools artifact available.\n"
    if not entries:
        return "TOOLS\n\nNo tool calls recorded.\n"

    lines = [
        "TOOLS",
        "",
        f"{len(entries)} calls · refreshed {fetch_time.strftime('%H:%M:%S')}",
        "",
    ]
    for entry in entries:
        pieces = [
            _format_timestamp(entry.recorded_at),
            _status_label(entry.status),
            entry.display_tool_name,
        ]
        if entry.compact_target:
            pieces.append(entry.compact_target)
        if _format_duration(entry.duration_ms):
            pieces.append(_format_duration(entry.duration_ms))
        lines.append(" | ".join(pieces))
        if entry.detail:
            lines.append(f"  {entry.detail}")
    lines.append("")
    return "\n".join(lines)


class AgentToolsPanel(Static):
    """Panel showing normalized tool-call artifacts for the selected agent."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_worker: Worker[tuple[ToolCallEntry, ...] | None] | None = None
        self._has_displayed_content: bool = False
        self._last_entries: tuple[ToolCallEntry, ...] | None = None
        self._last_fetch_time: datetime | None = None
        self._is_background_refreshing: bool = False

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
        cache_entry = peek_tool_calls_cache_entry(agent)

        if cache_entry is not None:
            self._display_tools_with_timestamp(
                cache_entry.entries,
                cache_entry.fetch_time,
                post_visibility_message=True,
            )
        else:
            self._show_loading()

        if should_throttle_tool_call_fetch(agent):
            return

        if self._current_worker is not None and self._current_worker.is_running:
            return

        mark_tool_call_fetch_started(agent)

        def fetch_task() -> tuple[ToolCallEntry, ...] | None:
            return self._fetch_tools_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def refresh_tools(self, agent: Agent) -> None:
        """Force refresh tool-call records for an agent."""
        self._current_agent = agent
        cache_entry = peek_tool_calls_cache_entry(agent)

        if cache_entry is not None:
            self._is_background_refreshing = True
            self._display_tools_with_timestamp(
                cache_entry.entries,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
            )
            # Force a re-read by invalidating the mtime watermark.
            invalidate_cached_tool_calls(agent)
        else:
            self._show_loading()

        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        def fetch_task() -> tuple[ToolCallEntry, ...] | None:
            return self._fetch_tools_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def get_tools_text(self) -> str | None:
        """Return a markdown/plain text timeline for editor actions."""
        if self._last_fetch_time is None:
            return None
        return _build_tools_timeline_markdown(self._last_entries, self._last_fetch_time)

    def show_empty(self) -> None:
        """Show empty state."""
        self._has_displayed_content = False
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
    ) -> None:
        self._last_entries = entries
        self._last_fetch_time = fetch_time

        if post_visibility_message:
            self.post_message(ToolsVisibilityChanged(has_tools=bool(entries)))

        self.update(_build_tools_timeline_text(entries, fetch_time, is_stale=is_stale))
        self._has_displayed_content = True

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
            if self._current_agent:
                cache_entry = peek_tool_calls_cache_entry(self._current_agent)
                if cache_entry is not None:
                    scroll_pos = self._save_scroll_position()
                    self._display_tools_with_timestamp(
                        cache_entry.entries,
                        cache_entry.fetch_time,
                        post_visibility_message=cache_entry.entries
                        != self._last_entries,
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
    "ToolsVisibilityChanged",
    "_ToolsCacheEntry",
    "_build_tools_timeline_markdown",
    "_build_tools_timeline_text",
    "_tools_cache",
    "get_cache_key",
]

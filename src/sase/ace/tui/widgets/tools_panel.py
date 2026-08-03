"""Agent tools panel widget for the ace TUI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.tools import (
    ToolCallEntry,
    build_cached_slow_tool_sources,
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.ace.tui.tools.cache import (
    ToolsCacheEntry,
    fetch_tool_calls_cached,
    get_cache_key,
    peek_tool_calls_cache_entry,
    tools_cache,
)
from sase.ace.tui.tools.slow import slow_tool_call_threshold_ms_from_widget
from sase.core.time import local_now

from ..util.trace import tui_trace
from ._tools_panel_fetching import (
    invalidate_tool_source_caches,
    latest_cached_fetch_time,
    mark_tool_source_fetch_started,
    should_throttle_tool_sources,
)
from ._tools_panel_time import format_timestamp
from ._tools_panel_timeline import (
    build_tools_timeline_markdown,
    build_tools_timeline_text,
    format_duration,
    rows_from_entries,
    rows_from_sources,
    status_label,
    status_style,
)
from ._tools_panel_types import (
    ToolDetailLevel,
    ToolTimelineRow,
    ToolsPanelFetchResult,
    coerce_detail_level,
    detail_level_label,
)

_ToolsCacheEntry = ToolsCacheEntry
_tools_cache = tools_cache
_ToolTimelineRow = ToolTimelineRow
_ToolsPanelFetchResult = ToolsPanelFetchResult
_build_tools_timeline_markdown = build_tools_timeline_markdown
_build_tools_timeline_text = build_tools_timeline_text
_coerce_detail_level = coerce_detail_level
_detail_level_label = detail_level_label
_format_duration = format_duration
_format_timestamp = format_timestamp
_rows_from_entries = rows_from_entries
_rows_from_sources = rows_from_sources
_status_label = status_label
_status_style = status_style


class ToolsVisibilityChanged(Message):
    """Message posted when tools panel availability changes."""

    def __init__(self, has_tools: bool) -> None:
        super().__init__()
        self.has_tools = has_tools


class AgentToolsPanel(Static):
    """Panel showing normalized tool-call artifacts for the selected agent."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_worker: Worker[ToolsPanelFetchResult] | None = None
        self._has_displayed_content: bool = False
        self._last_entries: tuple[ToolCallEntry, ...] | None = None
        self._last_rows: tuple[ToolTimelineRow, ...] | None = None
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
        next_level = coerce_detail_level(level)
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

        if should_throttle_tool_sources(agent):
            return

        if self._current_worker is not None and self._current_worker.is_running:
            return

        mark_tool_source_fetch_started(agent)

        def fetch_task() -> ToolsPanelFetchResult:
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
            invalidate_tool_source_caches(agent)
        else:
            self._show_loading()

        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        def fetch_task() -> ToolsPanelFetchResult:
            return self._fetch_tools_result_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def get_tools_text(self) -> str | None:
        """Return a markdown/plain text timeline for editor actions."""
        if self._last_fetch_time is None:
            return None
        return build_tools_timeline_markdown(
            self._last_entries,
            self._last_fetch_time,
            rows=self._last_rows,
            detail_level=self._detail_level,
            slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(self),
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
        rows: tuple[ToolTimelineRow, ...] | None = None,
    ) -> None:
        self._last_entries = entries
        self._last_rows = rows
        self._last_fetch_time = fetch_time

        if post_visibility_message:
            self.post_message(ToolsVisibilityChanged(has_tools=bool(entries)))

        self.update(
            build_tools_timeline_text(
                entries,
                fetch_time,
                is_stale=is_stale,
                rows=rows,
                detail_level=self._detail_level,
                slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(
                    self
                ),
            )
        )
        self._has_displayed_content = True

    def _display_tools_result(
        self,
        result: ToolsPanelFetchResult,
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

    def _cached_fetch_result(self, agent: Agent) -> ToolsPanelFetchResult | None:
        if supports_slow_tool_sources(agent):
            sources = build_cached_slow_tool_sources(agent)
            if sources is None:
                return None
            rows = rows_from_sources(sources)
            fetch_time = latest_cached_fetch_time(agent) or local_now()
            return ToolsPanelFetchResult(
                entries=None if rows is None else tuple(row.entry for row in rows),
                rows=rows,
                fetch_time=fetch_time,
            )

        cache_entry = peek_tool_calls_cache_entry(agent)
        if cache_entry is None:
            return None
        return ToolsPanelFetchResult(
            entries=cache_entry.entries,
            rows=rows_from_entries(cache_entry.entries),
            fetch_time=cache_entry.fetch_time,
        )

    def _fetch_tools_result_in_background(self, agent: Agent) -> ToolsPanelFetchResult:
        if supports_slow_tool_sources(agent):
            sources = build_slow_tool_sources(agent)
            rows = rows_from_sources(sources)
            return ToolsPanelFetchResult(
                entries=None if rows is None else tuple(row.entry for row in rows),
                rows=rows,
                fetch_time=latest_cached_fetch_time(agent) or local_now(),
            )

        entries = self._fetch_tools_in_background(agent)
        cache_entry = peek_tool_calls_cache_entry(agent)
        return ToolsPanelFetchResult(
            entries=entries,
            rows=rows_from_entries(entries),
            fetch_time=(
                cache_entry.fetch_time if cache_entry is not None else local_now()
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
            result = cast(ToolsPanelFetchResult, event.worker.result)
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

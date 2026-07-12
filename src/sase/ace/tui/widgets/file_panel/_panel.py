"""Agent file panel widget for the ace TUI."""

from datetime import datetime
from typing import Any

from textual.widgets import Static
from textual.worker import Worker

from ...models.agent import Agent
from ...util.trace import tui_trace
from ._content import FilePanelContentMixin, new_file_panel_render_cache
from ._display import FilePanelDisplayMixin, StaticReadResult
from ._fetch import FilePanelFetchMixin, InflightDiffKey
from ._file_list import FilePanelFileListMixin
from ._messages import (
    FileListChanged,
    _LIVE_DIFF_SENTINEL,
    file_cache,
    get_cache_key,
)
from ._state import FilePanelStateMixin


class AgentFilePanel(
    FilePanelFetchMixin,
    FilePanelFileListMixin,
    FilePanelContentMixin,
    FilePanelDisplayMixin,
    FilePanelStateMixin,
    Static,
):
    """Bottom panel showing agent file output (diffs, markdown, etc.)."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the file panel."""
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_worker: Worker[str | None] | None = None
        self._has_displayed_content: bool = False
        self._last_file_content: str | None = None
        self._is_background_refreshing: bool = False
        self._file_list: list[str] = []
        self._current_file_index: int = 0
        self._total_line_count: int = 0
        self._visible_line_count: int = 0
        self._is_content_capped: bool = False
        self._full_content: str | None = None
        self._full_content_lexer: str = "text"
        self._content_mode: str = "none"
        self._content_fetched_at: datetime | None = None
        self._content_render_cache = new_file_panel_render_cache()
        self._static_header_path: str | None = None
        self._linked_repo_name: str | None = None
        self._linked_workspace_dir: str | None = None
        self._linked_fetched_at: datetime | None = None
        self._current_image_renderable = None
        # Phase 6: dedupe in-flight diff workers across rapid re-selections of
        # the same agent. The in-flight key is intentionally cheap to compute
        # so navigation never performs workspace/provider discovery inline.
        self._inflight_diff_tasks: dict[InflightDiffKey, Worker[str | None]] = {}
        # Static-file/diff async reads. ``_static_request_id`` increments on
        # every schedule so the UI can drop superseded results when the user
        # navigates between files faster than reads complete.
        self._static_request_id: int = 0
        self._static_worker: Worker[StaticReadResult] | None = None

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        """Update with agent file output.

        Args:
            agent: The Agent to display file for.
            stale_threshold_seconds: Files older than this are refetched.
        """
        with tui_trace("widget.file_panel.update_display"):
            self._update_display_body(agent, stale_threshold_seconds)

    def _update_display_body(self, agent: Agent, stale_threshold_seconds: int) -> None:
        same_agent = (
            self._current_agent is not None
            and self._current_agent.identity == agent.identity
        )

        cache_key = get_cache_key(agent)
        cache_entry = file_cache.get(cache_key)

        if same_agent and cache_entry is not None:
            age_seconds = (datetime.now() - cache_entry.fetch_time).total_seconds()
            if age_seconds < stale_threshold_seconds:
                self._current_agent = agent
                self._reconcile_file_list(agent, allow_initial_display=True)
                return  # Fresh cache, same agent -- preserve rendered content
            # Stale cache, same agent -- start background worker only
            self._current_agent = agent
            self._reconcile_file_list(agent, allow_initial_display=True)
            self._is_background_refreshing = True
            if self._current_worker is not None and self._current_worker.is_running:
                self._current_worker.cancel()

            self._start_background_fetch(agent)
            return

        if (
            same_agent
            and self._current_worker is not None
            and self._current_worker.is_running
        ):
            # Same agent with an in-flight worker but no cache yet — let
            # the existing worker finish rather than cancelling and
            # restarting on every auto-refresh cycle.
            self._current_agent = agent
            self._reconcile_file_list(agent, allow_initial_display=True)
            return

        # Different agent or no cache -- full reset (existing behavior),
        # except when same_agent=True we preserve the user's current file by
        # path identity so auto-refresh doesn't clobber a <ctrl+n>/<ctrl+p>
        # selection.
        saved_path: str | None = None
        if (
            same_agent
            and self._file_list
            and 0 <= self._current_file_index < len(self._file_list)
        ):
            saved_path = self._file_list[self._current_file_index]

        self._current_agent = agent
        desired, default_value = self._desired_file_list(agent)
        self._reset_content_state()
        self._file_list = list(desired)
        self._current_file_index = self._select_file_index(
            self._file_list,
            preferred_value=saved_path,
            default_value=default_value,
        )

        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

        # If starting on a linked or static extra page, display it immediately
        # and fetch the primary diff in the background.
        if (
            self._file_list
            and self._file_list[self._current_file_index] != _LIVE_DIFF_SENTINEL
        ):
            self._display_file_at_current_index()
            self._start_background_fetch(agent)
            return

        if cache_entry is not None:
            age_seconds = (datetime.now() - cache_entry.fetch_time).total_seconds()
            if age_seconds < stale_threshold_seconds:
                # Cache is fresh - use it directly
                self._display_file_with_timestamp(
                    cache_entry.diff_output,
                    cache_entry.fetch_time,
                    post_visibility_message=True,
                )
                return

            # Cache is stale - display stale content while fetching in background
            self._is_background_refreshing = True
            self._display_file_with_timestamp(
                cache_entry.diff_output,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
            )
        else:
            # No cache - show loading for first-time loads
            self._show_loading()

        self._start_background_fetch(agent)

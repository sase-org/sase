"""Agent file panel widget for the ace TUI."""

import os
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ...models.agent import Agent
from ._diff import get_agent_diff
from ._display import FilePanelDisplayMixin
from ._messages import (
    FileListChanged,
    FileTrimChanged,
    FileVisibilityChanged,
    FileCacheEntry,
    _EXTENSION_TO_LEXER,
    file_cache,
    get_cache_key,
)
from ._trim import FilePanelTrimMixin


class AgentFilePanel(FilePanelTrimMixin, FilePanelDisplayMixin, Static):
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
        # Trim state
        self._total_line_count: int = 0
        self._visible_line_count: int = 0
        self._base_trim_size: int = 0
        self._is_trimmed: bool = False
        self._full_content: str | None = None
        self._full_content_lexer: str = "text"
        self._content_mode: str = "none"
        self._static_header_path: str | None = None

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        """Update with agent file output.

        Args:
            agent: The Agent to display file for.
            stale_threshold_seconds: Files older than this are refetched.
        """
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
                return  # Fresh cache, same agent -- preserve trim state
            # Stale cache, same agent -- start background worker only
            self._current_agent = agent
            self._is_background_refreshing = True
            if self._current_worker is not None and self._current_worker.is_running:
                self._current_worker.cancel()

            self._start_background_fetch(agent)
            return

        # Different agent or no cache -- full reset (existing behavior)
        self._reset_trim_state()
        self._current_agent = agent

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

    def set_file_list(self, files: list[str]) -> None:
        """Store the file list, reset index to 0, and display the first file.

        Args:
            files: Ordered list of file paths to make available for cycling.
        """
        # Cancel any running background worker to prevent it from overwriting
        # the static file display (e.g. stale live-diff from RUNNING phase)
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        self._reset_trim_state()
        if files == self._file_list:
            return
        self._file_list = list(files)
        self._current_file_index = 0
        self.post_message(
            FileListChanged(file_count=len(self._file_list), file_index=0)
        )
        if files:
            self._display_file_at_current_index()

    def next_file(self) -> None:
        """Cycle to the next file in the list (wraps around)."""
        if len(self._file_list) <= 1:
            return
        self._current_file_index = (self._current_file_index + 1) % len(self._file_list)
        self._display_file_at_current_index()
        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

    def prev_file(self) -> None:
        """Cycle to the previous file in the list (wraps around)."""
        if len(self._file_list) <= 1:
            return
        self._current_file_index = (self._current_file_index - 1) % len(self._file_list)
        self._display_file_at_current_index()
        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

    @property
    def current_file_count(self) -> int:
        """Return the number of files in the file list."""
        return len(self._file_list)

    @property
    def current_file_index(self) -> int:
        """Return the current file index (0-based)."""
        return self._current_file_index

    def _display_file_at_current_index(self) -> None:
        """Display the file at the current index using static file display."""
        if not self._file_list:
            return
        self.display_static_file(self._file_list[self._current_file_index])

    def _post_file_visibility(self, has_file: bool) -> None:
        """Post a FileVisibilityChanged message with current file list state."""
        file_count = len(self._file_list) if self._file_list else (1 if has_file else 0)
        self.post_message(
            FileVisibilityChanged(
                has_file=has_file,
                file_count=file_count,
                file_index=self._current_file_index,
            )
        )

    def refresh_file(self, agent: Agent) -> None:
        """Force refresh the file for an agent.

        Args:
            agent: The Agent to refresh file for.
        """
        self._current_agent = agent

        # Check for existing cache to display while refreshing
        cache_key = get_cache_key(agent)
        cache_entry = file_cache.get(cache_key)

        if cache_entry is not None and self._full_content is not None:
            # Existing content displayed -- update timestamp in-place
            self._is_background_refreshing = True
            self._update_timestamp_header(cache_entry.fetch_time, refreshing=True)
            if self._is_trimmed:
                self._render_trimmed_content()
            else:
                self._render_full_content()
        elif cache_entry is not None:
            # Cache exists but not yet displayed -- full display
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

    def _start_background_fetch(self, agent: Agent) -> None:
        """Cancel any running worker and start a new background fetch."""
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        def fetch_task() -> str | None:
            return self._fetch_file_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def _fetch_file_in_background(self, agent: Agent) -> str | None:
        """Fetch file output in background thread.

        Args:
            agent: The agent to get file for.

        Returns:
            File output string, or None if unavailable.
        """
        diff_output = get_agent_diff(agent)

        # Store in cache
        cache_key = get_cache_key(agent)
        file_cache[cache_key] = FileCacheEntry(
            diff_output=diff_output,
            fetch_time=datetime.now(),
        )

        return diff_output

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        if event.worker != self._current_worker:
            return

        # Always clear background refreshing flag when worker completes
        self._is_background_refreshing = False

        if event.state == WorkerState.SUCCESS:
            # Worker completed - display result from cache
            if self._current_agent:
                cache_key = get_cache_key(self._current_agent)
                if cache_key in file_cache:
                    cache_entry = file_cache[cache_key]

                    # Skip update if content hasn't changed (but only
                    # if we've displayed before — on first load, None==None
                    # would suppress the visibility message that hides us)
                    if (
                        self._has_displayed_content
                        and cache_entry.diff_output == self._last_file_content
                    ):
                        # Content unchanged - just update timestamp header
                        # and re-render with current trim state preserved
                        scroll_pos = self._save_scroll_position()
                        self._update_timestamp_header(cache_entry.fetch_time)
                        if self._is_trimmed:
                            self._render_trimmed_content()
                        else:
                            self._render_full_content()
                        self._restore_scroll_position(scroll_pos)
                    else:
                        # Content changed - save scroll, update, restore scroll
                        scroll_pos = self._save_scroll_position()
                        self._display_file_with_timestamp(
                            cache_entry.diff_output, cache_entry.fetch_time
                        )
                        self._restore_scroll_position(scroll_pos)
        elif event.state == WorkerState.ERROR:
            # Show error state
            text = Text()
            text.append("Error fetching file\n", style="bold red")
            text.append("The diff command failed or timed out.", style="dim")
            self.update(text)
        elif event.state == WorkerState.CANCELLED:
            # Cancelled - do nothing, new worker will handle display
            pass

    def get_current_file_path(self) -> str | None:
        """Return the expanded path of the currently displayed file, or None."""
        if self._file_list:
            return os.path.expanduser(self._file_list[self._current_file_index])
        return None

    def get_current_content(self) -> str | None:
        """Return the last displayed file content, or None."""
        return self._last_file_content


__all__ = [
    "AgentFilePanel",
    "FileListChanged",
    "FileTrimChanged",
    "FileVisibilityChanged",
    "_EXTENSION_TO_LEXER",
]

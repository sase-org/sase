"""Agent file panel widget for the ace TUI."""

import os
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.plan_chain import PLAN_CHAIN_PLAN_SUFFIX, canonical_plan_chain_suffix

from ...models.agent import Agent
from ...graphics import is_supported_image_path
from ...util.trace import tui_trace
from ._diff import get_agent_diff
from ._display import FilePanelDisplayMixin, StaticReadResult
from ._linked_commits import LinkedCommitGroup
from ._linked_deltas import LinkedDeltaGroup, get_cached_linked_delta_groups
from ._messages import (
    FileListChanged,
    FileTrimChanged,
    FileVisibilityChanged,
    FileCacheEntry,
    _EXTENSION_TO_LEXER,
    _LIVE_DIFF_SENTINEL,
    file_cache,
    get_cache_key,
    is_linked_slot,
    linked_slot_id,
    linked_slot_repo_name,
)
from ._trim import FilePanelTrimMixin
from ..prompt_panel._agent_context_common import WORKSPACE_GLYPH

InflightDiffKey = tuple[tuple[object, ...], int | None, str | None, str | None]


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
                return  # Fresh cache, same agent -- preserve trim state
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
        self._reset_trim_state()
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

    def set_file_list(self, files: list[str], start_index: int = 0) -> None:
        """Store the file list, reset index, and display a file.

        Args:
            files: Ordered list of file paths to make available for cycling.
            start_index: Initial file index to display (default 0).
        """
        # Cancel any running background worker to prevent it from overwriting
        # the static file display (e.g. stale live-diff from RUNNING phase)
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        # Clear agent association so that the next update_display() call for a
        # different agent won't incorrectly see same_agent=True and skip the
        # full reset (which would leave this static file list on screen).
        self._current_agent = None

        if files == self._file_list and self._file_list and self._has_displayed_content:
            # Files unchanged — preserve the user's current_file_index regardless
            # of the caller's default start_index. Auto-refresh must not overwrite
            # a user selection driven by <ctrl+n>/<ctrl+p>.
            return

        # Remember the file the user is currently on so we can preserve the
        # selection across refreshes where the list has grown/shrunk but the
        # current file still exists.
        old_path: str | None = None
        if self._file_list and 0 <= self._current_file_index < len(self._file_list):
            old_path = self._file_list[self._current_file_index]

        self._reset_trim_state()
        self._file_list = list(files)
        if old_path is not None and old_path in self._file_list:
            self._current_file_index = self._file_list.index(old_path)
        else:
            self._current_file_index = min(start_index, len(files) - 1) if files else 0
        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
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
        """Display the file at the current index.

        Handles live diff, linked diff, and static file page slots.
        """
        if not self._file_list:
            return
        path = self._file_list[self._current_file_index]
        if path == _LIVE_DIFF_SENTINEL:
            # Re-display the cached live diff
            if self._current_agent:
                cache_key = get_cache_key(self._current_agent)
                cache_entry = file_cache.get(cache_key)
                if cache_entry:
                    self._display_file_with_timestamp(
                        cache_entry.diff_output, cache_entry.fetch_time
                    )
            return
        if is_linked_slot(path):
            repo_name = linked_slot_repo_name(path)
            group = self._linked_group_for_repo(repo_name)
            if group is None:
                self.display_linked_diff_unavailable(repo_name)
                return
            self.display_linked_diff(
                group.repo_name,
                group.workspace_dir,
                group.diff_text,
                group.fetched_at,
            )
            return
        self.display_static_file(path)

    def _desired_file_list(self, agent: Agent) -> tuple[list[str], str | None]:
        """Return the current canonical file-panel page list and default page."""
        pages: list[str] = []

        cache_entry = file_cache.get(get_cache_key(agent))
        if cache_entry is not None and bool(cache_entry.diff_output):
            pages.append(_LIVE_DIFF_SENTINEL)

        linked_groups = get_cached_linked_delta_groups(agent)
        pages.extend(
            linked_slot_id(group.repo_name) for group in linked_groups if group.entries
        )

        extra_files = list(agent.extra_files)
        pages.extend(extra_files)

        default_value = pages[0] if pages else None
        if (
            extra_files
            and canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
            and not agent.diff_path
        ):
            default_value = extra_files[0]
        return pages, default_value

    def _select_file_index(
        self,
        pages: list[str],
        *,
        preferred_value: str | None,
        default_value: str | None,
        fallback_index: int = 0,
    ) -> int:
        """Pick an index by current page value, then default page, then clamp."""
        if not pages:
            return 0
        if preferred_value is not None and preferred_value in pages:
            return pages.index(preferred_value)
        if default_value is not None and default_value in pages:
            return pages.index(default_value)
        return min(max(fallback_index, 0), len(pages) - 1)

    def _current_file_value(self) -> str | None:
        if self._file_list and 0 <= self._current_file_index < len(self._file_list):
            return self._file_list[self._current_file_index]
        return None

    def _linked_group_for_repo(self, repo_name: str) -> LinkedDeltaGroup | None:
        agent = self._current_agent
        if agent is None:
            return None
        for group in get_cached_linked_delta_groups(agent):
            if group.repo_name == repo_name:
                return group
        return None

    def _current_linked_diff_changed(self) -> bool:
        current = self._current_file_value()
        if current is None or not is_linked_slot(current):
            return False
        group = self._linked_group_for_repo(linked_slot_repo_name(current))
        if group is None:
            return self._last_file_content is not None
        return group.diff_text != self._last_file_content

    def _reconcile_file_list(
        self,
        agent: Agent,
        *,
        allow_initial_display: bool,
    ) -> None:
        """Synchronize page slots with cached diff/link/artifact state."""
        self._current_agent = agent
        desired, default_value = self._desired_file_list(agent)
        current_value = self._current_file_value()

        if desired == self._file_list:
            if allow_initial_display and desired and not self._has_displayed_content:
                self._display_file_at_current_index()
            elif self._current_linked_diff_changed():
                scroll_pos = self._save_scroll_position()
                self._display_file_at_current_index()
                self._restore_scroll_position(scroll_pos)
            return

        old_index = self._current_file_index
        old_displayed = self._has_displayed_content
        self._file_list = list(desired)
        self._current_file_index = self._select_file_index(
            self._file_list,
            preferred_value=current_value,
            default_value=default_value,
            fallback_index=old_index,
        )
        new_value = self._current_file_value()

        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

        if not self._file_list:
            if allow_initial_display and current_value is not None:
                cache_entry = file_cache.get(get_cache_key(agent))
                if cache_entry is not None:
                    self._display_file_with_timestamp(
                        cache_entry.diff_output,
                        cache_entry.fetch_time,
                    )
                else:
                    self._post_file_visibility(has_file=False)
            return

        needs_render = new_value != current_value or not old_displayed
        if new_value is not None and is_linked_slot(new_value):
            needs_render = needs_render or self._current_linked_diff_changed()
        if allow_initial_display and needs_render:
            scroll_pos = self._save_scroll_position()
            self._display_file_at_current_index()
            if new_value == current_value:
                self._restore_scroll_position(scroll_pos)

    def _pick_up_extra_files(self, agent: Agent) -> None:
        """Backward-compatible wrapper for same-agent file-list reconciliation."""
        self._reconcile_file_list(agent, allow_initial_display=True)

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
        current = self._current_file_value()
        if current is not None and is_linked_slot(current):
            self._reconcile_file_list(agent, allow_initial_display=True)
            self._start_background_fetch(agent)
            return

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
        """Start a background fetch, attaching to in-flight workers when possible.

        Concurrent re-selects of the same agent share one worker rather than
        cancel-and-respawn. The full diff cache key is intentionally computed
        inside the worker by ``get_agent_diff``; deriving it here performs
        workspace/provider discovery on the UI thread and shows up directly in
        j/k latency.
        """
        inflight_key = self._inflight_key_for_agent(agent)
        existing = self._inflight_diff_tasks.get(inflight_key)
        if existing is not None and existing.is_running:
            self._current_worker = existing
            return

        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        def fetch_task() -> str | None:
            return self._fetch_file_in_background(agent)

        worker = self.run_worker(fetch_task, thread=True)
        self._current_worker = worker
        self._inflight_diff_tasks[inflight_key] = worker

    def _inflight_key_for_agent(self, agent: Agent) -> InflightDiffKey:
        """Return a cheap no-I/O key for in-flight diff worker reuse."""
        return (
            agent.identity,
            agent.workspace_num,
            agent.workspace_dir,
            agent.diff_path,
        )

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
        # Static-read workers carry a StaticReadResult and are dispatched
        # independently of the diff worker pipeline. Stragglers from
        # cancelled/superseded reads are caught by the result-type check
        # even after ``_static_worker`` has moved on.
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, StaticReadResult):
                self._handle_static_read_result(result)
                if event.worker is self._static_worker:
                    self._static_worker = None
                return
        if event.worker is self._static_worker and event.state in (
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            self._static_worker = None
            return

        if event.state in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            # Drop any inflight-task entries pointing at this worker so the
            # next selection of the same key starts a fresh fetch.
            stale_keys = [
                k for k, w in self._inflight_diff_tasks.items() if w is event.worker
            ]
            for k in stale_keys:
                self._inflight_diff_tasks.pop(k, None)

        if event.worker != self._current_worker:
            return

        # Always clear background refreshing flag when worker completes
        self._is_background_refreshing = False

        if event.state == WorkerState.SUCCESS:
            if self._current_agent is not None:
                self._reconcile_file_list(
                    self._current_agent,
                    allow_initial_display=False,
                )

            # If the user is viewing a linked/static page (not the live diff),
            # don't overwrite it with the refreshed diff content.
            if self._file_list and (
                self._current_file_index >= len(self._file_list)
                or self._file_list[self._current_file_index] != _LIVE_DIFF_SENTINEL
            ):
                return

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
                        and self._full_content is not None
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
            path = self._file_list[self._current_file_index]
            if path == _LIVE_DIFF_SENTINEL or is_linked_slot(path):
                return None
            return os.path.expanduser(path)
        return None

    def current_source_label(self) -> str | None:
        """Return a short label for the currently selected file-panel source."""
        current = self._current_file_value()
        if current is None:
            return None
        if current == _LIVE_DIFF_SENTINEL:
            return "diff"
        if is_linked_slot(current):
            return f"{WORKSPACE_GLYPH} {linked_slot_repo_name(current)}"
        expanded = os.path.expanduser(current)
        return os.path.basename(expanded) or expanded

    def get_current_image_path(self) -> str | None:
        """Return the current existing image file path, or None."""
        path = self.get_current_file_path()
        if path is None:
            return None
        if not is_supported_image_path(path):
            return None
        if not os.path.exists(path):
            return None
        return path

    def get_current_content(self) -> str | None:
        """Return the last displayed file content, or None."""
        return self._last_file_content


__all__ = [
    "AgentFilePanel",
    "FileListChanged",
    "FileTrimChanged",
    "FileVisibilityChanged",
    "_EXTENSION_TO_LEXER",
    "_LIVE_DIFF_SENTINEL",
]

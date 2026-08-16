"""Background diff fetching for the agent file panel."""

from datetime import datetime

from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.core.time import local_now

from ...models.agent import Agent
from ._diff import get_agent_diff
from ._display import StaticReadResult
from ._messages import (
    FileCacheEntry,
    _LIVE_DIFF_SENTINEL,
    file_cache,
    get_cache_key,
    is_commit_slot,
    is_linked_slot,
)

InflightDiffKey = tuple[tuple[object, ...], int | None, str | None, str | None]


class FilePanelFetchMixin:
    """Mixin for live-diff refreshes and worker completion handling."""

    _current_agent: Agent | None
    _current_worker: Worker[str | None] | None
    _file_list: list[str]
    _current_file_index: int
    _has_displayed_content: bool
    _last_file_content: str | None
    _is_background_refreshing: bool
    _full_content: str | None
    _content_fetched_at: datetime | None
    _inflight_diff_tasks: dict[InflightDiffKey, Worker[str | None]]
    _static_worker: Worker[StaticReadResult] | None
    _anchor_agent_identity: object | None

    def refresh_file(self, agent: Agent) -> None:
        """Force refresh the file for an agent.

        Args:
            agent: The Agent to refresh file for.
        """
        self._current_agent = agent
        self._anchor_agent_identity = agent.identity
        current = self._current_file_value()  # type: ignore[attr-defined]
        if current is not None and (is_commit_slot(current) or is_linked_slot(current)):
            self._reconcile_file_list(  # type: ignore[attr-defined]
                agent, allow_initial_display=True
            )
            self._start_background_fetch(agent)
            return

        # Check for existing cache to display while refreshing
        cache_key = get_cache_key(agent)
        cache_entry = file_cache.get(cache_key)

        if cache_entry is not None and self._full_content is not None:
            # Existing content displayed -- update only the separate header.
            self._is_background_refreshing = True
            self._content_fetched_at = cache_entry.fetch_time  # type: ignore[attr-defined]
            self._render_full_content(refreshing=True)  # type: ignore[attr-defined]
        elif cache_entry is not None:
            # Cache exists but not yet displayed -- full display
            self._is_background_refreshing = True
            self._display_file_with_timestamp(  # type: ignore[attr-defined]
                cache_entry.diff_output,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
            )
        else:
            # No cache - show loading for first-time loads
            self._show_loading()  # type: ignore[attr-defined]

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

        worker = self.run_worker(fetch_task, thread=True)  # type: ignore[attr-defined]
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
            fetch_time=local_now(),
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
                self._handle_static_read_result(result)  # type: ignore[attr-defined]
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
                self._reconcile_file_list(  # type: ignore[attr-defined]
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
                        # Content unchanged: rebuild the small timestamp/header
                        # group while reusing the cached body renderable. The
                        # scroll-anchor funnel inside _render_full_content
                        # preserves the reader's position automatically.
                        self._content_fetched_at = cache_entry.fetch_time  # type: ignore[attr-defined]
                        self._render_full_content()  # type: ignore[attr-defined]
                    else:
                        self._display_file_with_timestamp(  # type: ignore[attr-defined]
                            cache_entry.diff_output, cache_entry.fetch_time
                        )
        elif event.state == WorkerState.ERROR:
            # Show error state
            text = Text()
            text.append("Error fetching file\n", style="bold red")
            text.append("The diff command failed or timed out.", style="dim")
            self._update_body(text)  # type: ignore[attr-defined]
        elif event.state == WorkerState.CANCELLED:
            # Cancelled - do nothing, new worker will handle display
            pass

"""Agent artifact-file viewer actions for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections import OrderedDict
from collections.abc import Callable
from types import FrameType
from typing import TYPE_CHECKING, Any

from ._panel_types import (
    ARTIFACT_FILE_NOTIFY_PID_ENV,
    ARTIFACT_FILE_VIEWER_LAYOUT_CLASS,
    ARTIFACT_FILE_VIEWER_NAV_MESSAGE,
    TabName,
)

# Hard cap on the per-row artifact-file cache. Each cache key folds in the
# agent identity, status, and marker-file mtime/size so status transitions
# create new keys; without a cap the dict grew unbounded over a session.
ARTIFACT_FILE_PAGE_CACHE_MAX = 256

if TYPE_CHECKING:
    from ...graphics import ArtifactFileViewerResult, TmuxPaneDecorationState
    from ...models import Agent
    from ...models.agent import AgentType


log = logging.getLogger(__name__)


class AgentPanelArtifactFileMixin:
    """Mixin providing artifact-file viewer actions and tmux pane tracking."""

    current_tab: TabName
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _artifact_file_tmux_pane_id: str | None
    _artifact_file_tmux_decoration_state: TmuxPaneDecorationState | None
    _artifact_file_viewer_previous_sigusr1_handler: (
        signal.Handlers | int | Callable[[int, FrameType | None], Any] | None
    )
    _artifact_file_discovery_inflight: dict[tuple[Any, ...], asyncio.Task[Any]]
    _artifact_file_page_cache: OrderedDict[tuple[Any, ...], list[Any]]

    def _install_artifact_file_viewer_close_signal_handler(self) -> bool:
        """Install the one-shot close notification handler if SIGUSR1 exists."""
        if not hasattr(signal, "SIGUSR1"):
            return False
        if (
            getattr(self, "_artifact_file_viewer_previous_sigusr1_handler", None)
            is not None
        ):
            return True

        def _handle_close(_signum: int, _frame: FrameType | None) -> None:
            self._schedule_artifact_file_viewer_closed_from_signal()

        try:
            previous = signal.signal(signal.SIGUSR1, _handle_close)
        except (OSError, RuntimeError, ValueError):
            return False
        self._artifact_file_viewer_previous_sigusr1_handler = previous  # type: ignore[attr-defined]
        return True

    def _restore_artifact_file_viewer_close_signal_handler(self) -> None:
        """Restore the SIGUSR1 handler that was active before Ace installed ours."""
        previous = getattr(self, "_artifact_file_viewer_previous_sigusr1_handler", None)
        if previous is None or not hasattr(signal, "SIGUSR1"):
            return
        try:
            signal.signal(signal.SIGUSR1, previous)
        except (OSError, RuntimeError, ValueError):
            pass
        self._artifact_file_viewer_previous_sigusr1_handler = None  # type: ignore[attr-defined]

    def _schedule_artifact_file_viewer_closed_from_signal(self) -> None:
        """Schedule the cheap UI update for an artifact-file viewer close."""
        call_later = getattr(self, "call_later", None)
        if callable(call_later):
            try:
                call_later(self._clear_artifact_file_viewer_layout_from_signal)
                return
            except Exception:
                pass
        self._clear_artifact_file_viewer_layout_from_signal()

    def _clear_artifact_file_viewer_layout_from_signal(self) -> None:
        """Clear tracked artifact-file pane state without querying tmux."""
        self._clear_tracked_artifact_file_tmux_pane_state(notify_warnings=False)

    def _restore_artifact_file_tmux_decoration(self, *, notify_warnings: bool) -> None:
        """Restore tmux decoration for the tracked artifact-file pane."""
        state = getattr(self, "_artifact_file_tmux_decoration_state", None)
        if state is None:
            return
        self._artifact_file_tmux_decoration_state = None  # type: ignore[attr-defined]

        from ...graphics import restore_artifact_file_tmux_pane_decoration

        result = restore_artifact_file_tmux_pane_decoration(state)
        if notify_warnings and result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _clear_tracked_artifact_file_tmux_pane_state(
        self,
        *,
        notify_warnings: bool = False,
    ) -> None:
        """Clear tracked artifact-file pane state and restore decoration."""
        self._restore_artifact_file_tmux_decoration(notify_warnings=notify_warnings)
        self._artifact_file_tmux_pane_id = None  # type: ignore[attr-defined]
        self._set_artifact_file_viewer_layout_collapsed(False)

    def _track_artifact_file_tmux_pane(self, pane_id: str) -> None:
        """Track an artifact-file pane and install tmux focus decoration."""
        self._clear_tracked_artifact_file_tmux_pane_state(notify_warnings=False)
        self._artifact_file_tmux_pane_id = pane_id  # type: ignore[attr-defined]

        from ...graphics import decorate_artifact_file_tmux_panes

        result = decorate_artifact_file_tmux_panes(pane_id)
        self._artifact_file_tmux_decoration_state = result.state  # type: ignore[attr-defined]
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]
        self._sync_artifact_file_viewer_layout()

    def _with_artifact_file_viewer_notify_pid(
        self,
        callback: Callable[[], ArtifactFileViewerResult],
    ) -> ArtifactFileViewerResult:
        """Run a tmux launch while exposing this Ace process as notify target."""
        if not self._install_artifact_file_viewer_close_signal_handler():
            return callback()

        previous = os.environ.get(ARTIFACT_FILE_NOTIFY_PID_ENV)
        os.environ[ARTIFACT_FILE_NOTIFY_PID_ENV] = str(os.getpid())
        try:
            return callback()
        finally:
            if previous is None:
                os.environ.pop(ARTIFACT_FILE_NOTIFY_PID_ENV, None)
            else:
                os.environ[ARTIFACT_FILE_NOTIFY_PID_ENV] = previous

    def _set_artifact_file_viewer_layout_collapsed(self, collapsed: bool) -> None:
        """Apply the Agents-tab layout state for the artifact-file pane."""
        try:
            content = self.query_one("#agents-content")  # type: ignore[attr-defined]
        except Exception:
            return
        if collapsed:
            content.add_class(ARTIFACT_FILE_VIEWER_LAYOUT_CLASS)
        else:
            content.remove_class(ARTIFACT_FILE_VIEWER_LAYOUT_CLASS)

    def _artifact_file_tmux_pane_visible(self) -> bool:
        """Return whether the tracked artifact-file pane is visible."""
        from ...graphics import artifact_file_tmux_pane_exists, is_tmux_session

        pane_id = getattr(self, "_artifact_file_tmux_pane_id", None)
        if pane_id is None:
            return False
        if not is_tmux_session():
            self._clear_tracked_artifact_file_tmux_pane_state(notify_warnings=False)
            return False
        if not artifact_file_tmux_pane_exists(pane_id):
            self._clear_tracked_artifact_file_tmux_pane_state(notify_warnings=False)
            return False
        return True

    def _sync_artifact_file_viewer_layout(self) -> None:
        """Keep the Agents side panel collapsed while a tracked pane is live."""
        self._set_artifact_file_viewer_layout_collapsed(
            self._artifact_file_tmux_pane_visible()
        )

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        """Block row-changing Agents navigation while an artifact-file pane is live."""
        if getattr(self, "current_tab", "agents") != "agents":
            return False
        if not self._artifact_file_tmux_pane_visible():
            return False
        self.notify(ARTIFACT_FILE_VIEWER_NAV_MESSAGE, severity="warning")  # type: ignore[attr-defined]
        return True

    def _focus_tracked_artifact_file_tmux_pane(self) -> bool:
        """Focus the artifact-file pane when the Agents split is live."""
        if getattr(self, "current_tab", "agents") != "agents":
            return False
        if not self._artifact_file_tmux_pane_visible():
            return False

        from ...graphics import select_tmux_pane

        pane_id = getattr(self, "_artifact_file_tmux_pane_id", None)
        if pane_id is None:
            return False
        result = select_tmux_pane(pane_id)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]
            self._sync_artifact_file_viewer_layout()
        return True

    def _ensure_artifact_file_page_cache(
        self,
    ) -> OrderedDict[tuple[Any, ...], list[Any]]:
        """Return (and lazily create) the per-row artifact-file cache."""
        cache: OrderedDict[tuple[Any, ...], list[Any]] | None = getattr(
            self, "_artifact_file_page_cache", None
        )
        if cache is None:
            cache = OrderedDict()
            self._artifact_file_page_cache = cache  # type: ignore[attr-defined]
        return cache

    def _artifact_file_cache_put(
        self,
        cache: OrderedDict[tuple[Any, ...], list[Any]],
        key: tuple[Any, ...],
        value: list[Any],
    ) -> None:
        """Write *value* and evict the oldest entry when the cap is exceeded."""
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > ARTIFACT_FILE_PAGE_CACHE_MAX:
            cache.popitem(last=False)

    def _cached_artifact_files(self, agent: Agent | None) -> list[Any] | None:
        """Probe the artifact-file cache without touching the disk.

        Returns ``None`` on cache miss so the caller can choose whether to
        schedule a background discovery; returns a copy of the cached list on
        hit (which may be empty when the agent has no artifact files).
        """
        if agent is None:
            return None
        identity = getattr(agent, "identity", None)
        if identity is None:
            return None
        cache = getattr(self, "_artifact_file_page_cache", None)
        if cache is None:
            return None
        row_key = self._artifact_file_cache_key(agent, identity)
        cached = cache.get(row_key)
        if cached is None:
            return None
        cache.move_to_end(row_key)
        return list(cached)

    def _list_selected_artifact_files(self, agent: Agent | None) -> list[Any]:
        """Return artifact files for *agent* without UI side effects."""
        if agent is None:
            return []
        cache = self._ensure_artifact_file_page_cache()

        identity = getattr(agent, "identity", None)
        if identity is None:
            artifacts_dir = agent.get_artifacts_dir()
            if artifacts_dir is None:
                return []
            from sase.core.artifact_file_facade import list_artifact_files

            try:
                return list_artifact_files(artifacts_dir)
            except Exception:
                return []

        cached = self._cached_artifact_files(agent)
        if cached is not None:
            return cached
        from ._artifact_file_provider import read_artifact_files_for_tui

        try:
            result = read_artifact_files_for_tui(agent)
        except Exception:
            return []
        page = result.value
        request = getattr(page, "request", None)
        generation = getattr(self, "_artifact_file_selection_generation", None)
        if (
            request is not None
            and generation is not None
            and not generation.accepts(request)
        ):
            return []
        artifact_files = list(page.artifact_files)
        row_key = self._artifact_file_cache_key(agent, identity)
        self._artifact_file_cache_put(cache, row_key, artifact_files)
        self._artifact_file_provider_used_daemon = False  # type: ignore[attr-defined]
        self._artifact_file_provider_snapshot = page.shared_snapshot  # type: ignore[attr-defined]
        return artifact_files

    def _schedule_artifact_file_discovery(self, agent: Agent | None) -> None:
        """Schedule artifact-file discovery for *agent* off the UI thread.

        No-op when discovery for the agent's current cache row is already
        in flight. The continuation populates the artifact-file cache and, if the
        selection is unchanged, refreshes only the footer binding state.
        """
        if agent is None:
            return
        identity = getattr(agent, "identity", None)
        if identity is None:
            return
        row_key = self._artifact_file_cache_key(agent, identity)
        inflight: dict[tuple[Any, ...], asyncio.Task[Any]] | None = getattr(
            self, "_artifact_file_discovery_inflight", None
        )
        if inflight is None:
            inflight = {}
            self._artifact_file_discovery_inflight = inflight  # type: ignore[attr-defined]
        if row_key in inflight:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        coro = self._run_artifact_file_discovery(agent, row_key)
        task = loop.create_task(coro)
        inflight[row_key] = task

    async def _run_artifact_file_discovery(
        self,
        agent: Agent,
        row_key: tuple[Any, ...],
    ) -> None:
        """Worker body for off-thread artifact-file discovery."""
        from ._artifact_file_provider import read_artifact_files_for_tui

        try:
            try:
                result = await asyncio.to_thread(read_artifact_files_for_tui, agent)
                artifact_files = list(result.value.artifact_files)
            except Exception:
                log.debug("background artifact-file discovery failed", exc_info=True)
                artifact_files = []
            cache = self._ensure_artifact_file_page_cache()
            self._artifact_file_cache_put(cache, row_key, artifact_files)
            current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if current_agent is None:
                return
            current_identity = getattr(current_agent, "identity", None)
            if current_identity is None:
                return
            current_row_key = self._artifact_file_cache_key(
                current_agent, current_identity
            )
            if current_row_key != row_key:
                return
            refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh_footer):
                try:
                    refresh_footer()
                except Exception:
                    log.debug("post-discovery footer refresh failed", exc_info=True)
        finally:
            inflight: dict[tuple[Any, ...], asyncio.Task[Any]] | None = getattr(
                self, "_artifact_file_discovery_inflight", None
            )
            if inflight is not None:
                inflight.pop(row_key, None)

    def _cancel_pending_artifact_file_discovery(self) -> None:
        """Cancel in-flight artifact-file discovery tasks (shutdown hook)."""
        inflight: dict[tuple[Any, ...], asyncio.Task[Any]] | None = getattr(
            self, "_artifact_file_discovery_inflight", None
        )
        if not inflight:
            return
        for task in list(inflight.values()):
            if not task.done():
                task.cancel()
        inflight.clear()

    def _artifact_file_cache_key(
        self,
        agent: Agent,
        identity: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        """Return cache-key state that changes when artifact files can change."""
        artifacts_dir = agent.get_artifacts_dir()
        marker_stats: list[tuple[str, int | None, int | None]] = []
        if artifacts_dir is not None:
            for marker in (
                "done.json",
                "agent_meta.json",
                "plan_path.json",
                os.path.join("markdown_pdfs", "index.json"),
            ):
                marker_path = os.path.join(artifacts_dir, marker)
                try:
                    stat = os.stat(marker_path)
                    marker_stats.append((marker, stat.st_mtime_ns, stat.st_size))
                except OSError:
                    marker_stats.append((marker, None, None))

        return (
            *(str(part) for part in identity),
            getattr(agent, "status", None),
            getattr(agent, "diff_path", None),
            getattr(agent, "response_path", None),
            tuple(getattr(agent, "extra_files", ()) or ()),
            artifacts_dir,
            tuple(marker_stats),
        )

    def _open_artifact_file(self, artifact_file: Any, *, zoom: bool = False) -> None:
        from ...graphics import (
            is_tmux_session,
            view_registered_artifact_file,
            view_registered_artifact_file_in_tmux_pane,
        )

        if is_tmux_session():

            def tmux_callback() -> ArtifactFileViewerResult:
                if zoom:
                    return view_registered_artifact_file_in_tmux_pane(
                        artifact_file, zoom=True
                    )
                return view_registered_artifact_file_in_tmux_pane(artifact_file)

            result = self._with_artifact_file_viewer_notify_pid(tmux_callback)
            if result.ok and result.pane_id is not None:
                self._track_artifact_file_tmux_pane(result.pane_id)
        else:
            from ...util.external_tool import suspend_for_external_tool

            with suspend_for_external_tool(
                self,
                action="open_artifact_file",
                tool_kind="artifact_file_viewer",
                path_count=1,
                status_message="Opening artifact file…",
            ):
                result = view_registered_artifact_file(artifact_file)
            if zoom:
                self.notify(  # type: ignore[attr-defined]
                    "Zoom open is only available inside tmux",
                    severity="warning",
                )
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _open_artifact_files(
        self,
        artifact_files: list[Any],
        *,
        zoom: bool = False,
    ) -> None:
        if not artifact_files:
            return
        if len(artifact_files) == 1:
            self._open_artifact_file(artifact_files[0], zoom=zoom)
            return

        from ...graphics import (
            is_tmux_session,
            view_registered_artifact_files,
            view_registered_artifact_files_in_tmux_pane,
        )

        if is_tmux_session():

            def tmux_callback() -> ArtifactFileViewerResult:
                if zoom:
                    return view_registered_artifact_files_in_tmux_pane(
                        artifact_files, zoom=True
                    )
                return view_registered_artifact_files_in_tmux_pane(artifact_files)

            result = self._with_artifact_file_viewer_notify_pid(tmux_callback)
            if result.ok and result.pane_id is not None:
                self._track_artifact_file_tmux_pane(result.pane_id)
        else:
            from ...util.external_tool import suspend_for_external_tool

            with suspend_for_external_tool(
                self,
                action="open_artifact_files",
                tool_kind="artifact_file_viewer",
                path_count=len(artifact_files),
                status_message=f"Opening {len(artifact_files)} artifact files…",
            ):
                result = view_registered_artifact_files(artifact_files)
            if zoom:
                self.notify(  # type: ignore[attr-defined]
                    "Zoom open is only available inside tmux",
                    severity="warning",
                )
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _toggle_tracked_artifact_file_tmux_pane(self) -> bool:
        """Close a live tracked artifact-file pane, returning whether it closed."""
        from ...graphics import (
            artifact_file_tmux_pane_exists,
            close_artifact_file_tmux_pane,
            is_tmux_session,
        )

        if not is_tmux_session():
            return False

        pane_id = getattr(self, "_artifact_file_tmux_pane_id", None)
        if pane_id is None:
            return False
        if not artifact_file_tmux_pane_exists(pane_id):
            self._clear_tracked_artifact_file_tmux_pane_state(notify_warnings=False)
            return False

        self._restore_artifact_file_tmux_decoration(notify_warnings=True)
        result = close_artifact_file_tmux_pane(pane_id)
        self._artifact_file_tmux_pane_id = None  # type: ignore[attr-defined]
        self._set_artifact_file_viewer_layout_collapsed(False)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]
        return True

    def _focus_agent_list_after_artifact_modal(self) -> None:
        if self.current_tab != "agents":
            return
        try:
            from ...widgets import AgentList

            self.query_one("#agent-list-panel", AgentList).focus()  # type: ignore[attr-defined]
        except Exception:
            return

    def _artifact_file_prefix_label(self, agent: Agent) -> str:
        """Return a short, human-readable prefix to identify *agent* in the picker."""
        name = agent.display_name or ""
        agent_name = getattr(agent, "agent_name", None) or ""
        if agent_name and agent_name != name:
            return f"{name} @{agent_name}" if name else f"@{agent_name}"
        return name

    def _collect_marked_artifact_files(
        self,
    ) -> tuple[list[Any], list[str | None], int]:
        """Return artifact files, labels, and the marked-agent count."""
        marked: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        artifact_files: list[Any] = []
        labels: list[str | None] = []
        for agent in marked:
            agent_label = self._artifact_file_prefix_label(agent)
            for artifact_file in self._list_selected_artifact_files(agent):
                artifact_files.append(artifact_file)
                labels.append(agent_label)
        return artifact_files, labels, len(marked)

    def action_open_artifact_files(self) -> None:
        """Open or choose artifact files associated with the selected agent."""
        if self.current_tab != "agents":
            return
        if self._toggle_tracked_artifact_file_tmux_pane():
            return

        from ...modals import ArtifactFileSelectionModal

        def _open_selected(selection: Any) -> None:
            try:
                selected_artifact_files, zoom = self._normalize_artifact_file_selection(
                    selection
                )
                if selected_artifact_files:
                    self._open_artifact_files(selected_artifact_files, zoom=zoom)
            finally:
                self._focus_agent_list_after_artifact_modal()

        if self._marked_agents:
            artifact_files, labels, marked_count = self._collect_marked_artifact_files()
            if marked_count == 0:
                self.notify(  # type: ignore[attr-defined]
                    "No marked agents remain",
                    severity="warning",
                )
                return
            if not artifact_files:
                self.notify(  # type: ignore[attr-defined]
                    "No artifact files found in marked agents",
                    severity="warning",
                )
                return
            self.push_screen(  # type: ignore[attr-defined]
                ArtifactFileSelectionModal(
                    artifact_files,
                    agent_labels=labels,
                    agent_count=marked_count,
                ),
                _open_selected,
            )
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        artifact_files = self._list_selected_artifact_files(agent)
        if not artifact_files:
            message = (
                "No completed artifact files for this agent"
                if agent.status not in ("DONE", "FAILED")
                else "No artifact files found"
            )
            self.notify(message, severity="warning")  # type: ignore[attr-defined]
            return

        self.push_screen(ArtifactFileSelectionModal(artifact_files), _open_selected)  # type: ignore[attr-defined]

    def _normalize_artifact_file_selection(
        self,
        selection: Any,
    ) -> tuple[list[Any], bool]:
        from ...modals import ArtifactFileSelectionResult

        if selection is None:
            return [], False
        if isinstance(selection, ArtifactFileSelectionResult):
            return selection.artifact_files, selection.zoom
        if isinstance(selection, list):
            return selection, False
        return [selection], False

    def action_view_image(self) -> None:
        """Compatibility wrapper for older keymaps."""
        self.action_open_artifact_files()

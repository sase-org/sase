"""Agent artifact viewer actions for the ace TUI app."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from types import FrameType
from typing import TYPE_CHECKING, Any

from ._panel_types import (
    ARTIFACT_NOTIFY_PID_ENV,
    ARTIFACT_VIEWER_LAYOUT_CLASS,
    ARTIFACT_VIEWER_NAV_MESSAGE,
    TabName,
)

if TYPE_CHECKING:
    from ...graphics import ArtifactViewerResult, TmuxPaneDecorationState
    from ...models import Agent
    from ...models.agent import AgentType


class AgentPanelArtifactMixin:
    """Mixin providing agent artifact viewer actions and tmux pane tracking."""

    current_tab: TabName
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _artifact_tmux_pane_id: str | None
    _artifact_tmux_decoration_state: TmuxPaneDecorationState | None
    _artifact_viewer_previous_sigusr1_handler: (
        signal.Handlers | int | Callable[[int, FrameType | None], Any] | None
    )

    def _install_artifact_viewer_close_signal_handler(self) -> bool:
        """Install the one-shot close notification handler if SIGUSR1 exists."""
        if not hasattr(signal, "SIGUSR1"):
            return False
        if getattr(self, "_artifact_viewer_previous_sigusr1_handler", None) is not None:
            return True

        def _handle_close(_signum: int, _frame: FrameType | None) -> None:
            self._schedule_artifact_viewer_closed_from_signal()

        try:
            previous = signal.signal(signal.SIGUSR1, _handle_close)
        except (OSError, RuntimeError, ValueError):
            return False
        self._artifact_viewer_previous_sigusr1_handler = previous  # type: ignore[attr-defined]
        return True

    def _restore_artifact_viewer_close_signal_handler(self) -> None:
        """Restore the SIGUSR1 handler that was active before Ace installed ours."""
        previous = getattr(self, "_artifact_viewer_previous_sigusr1_handler", None)
        if previous is None or not hasattr(signal, "SIGUSR1"):
            return
        try:
            signal.signal(signal.SIGUSR1, previous)
        except (OSError, RuntimeError, ValueError):
            pass
        self._artifact_viewer_previous_sigusr1_handler = None  # type: ignore[attr-defined]

    def _schedule_artifact_viewer_closed_from_signal(self) -> None:
        """Schedule the cheap UI update for a tmux artifact viewer close event."""
        call_later = getattr(self, "call_later", None)
        if callable(call_later):
            try:
                call_later(self._clear_artifact_viewer_layout_from_signal)
                return
            except Exception:
                pass
        self._clear_artifact_viewer_layout_from_signal()

    def _clear_artifact_viewer_layout_from_signal(self) -> None:
        """Clear tracked artifact pane state without querying tmux."""
        self._clear_tracked_artifact_tmux_pane_state(notify_warnings=False)

    def _restore_artifact_tmux_decoration(self, *, notify_warnings: bool) -> None:
        """Restore tmux decoration once for the currently tracked artifact pane."""
        state = getattr(self, "_artifact_tmux_decoration_state", None)
        if state is None:
            return
        self._artifact_tmux_decoration_state = None  # type: ignore[attr-defined]

        from ...graphics import restore_artifact_tmux_pane_decoration

        result = restore_artifact_tmux_pane_decoration(state)
        if notify_warnings and result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _clear_tracked_artifact_tmux_pane_state(
        self,
        *,
        notify_warnings: bool = False,
    ) -> None:
        """Clear tracked artifact pane state and restore tmux decoration."""
        self._restore_artifact_tmux_decoration(notify_warnings=notify_warnings)
        self._artifact_tmux_pane_id = None  # type: ignore[attr-defined]
        self._set_artifact_viewer_layout_collapsed(False)

    def _track_artifact_tmux_pane(self, pane_id: str) -> None:
        """Track a launched artifact pane and install tmux focus decoration."""
        self._clear_tracked_artifact_tmux_pane_state(notify_warnings=False)
        self._artifact_tmux_pane_id = pane_id  # type: ignore[attr-defined]

        from ...graphics import decorate_artifact_tmux_panes

        result = decorate_artifact_tmux_panes(pane_id)
        self._artifact_tmux_decoration_state = result.state  # type: ignore[attr-defined]
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]
        self._sync_artifact_viewer_layout()

    def _with_artifact_viewer_notify_pid(
        self,
        callback: Callable[[], ArtifactViewerResult],
    ) -> ArtifactViewerResult:
        """Run a tmux launch while exposing this Ace process as notify target."""
        if not self._install_artifact_viewer_close_signal_handler():
            return callback()

        previous = os.environ.get(ARTIFACT_NOTIFY_PID_ENV)
        os.environ[ARTIFACT_NOTIFY_PID_ENV] = str(os.getpid())
        try:
            return callback()
        finally:
            if previous is None:
                os.environ.pop(ARTIFACT_NOTIFY_PID_ENV, None)
            else:
                os.environ[ARTIFACT_NOTIFY_PID_ENV] = previous

    def _set_artifact_viewer_layout_collapsed(self, collapsed: bool) -> None:
        """Apply the Agents-tab layout state for the tracked artifact pane."""
        try:
            content = self.query_one("#agents-content")  # type: ignore[attr-defined]
        except Exception:
            return
        if collapsed:
            content.add_class(ARTIFACT_VIEWER_LAYOUT_CLASS)
        else:
            content.remove_class(ARTIFACT_VIEWER_LAYOUT_CLASS)

    def _artifact_tmux_pane_visible(self) -> bool:
        """Return whether the tracked artifact tmux pane is currently visible."""
        from ...graphics import artifact_tmux_pane_exists, is_tmux_session

        pane_id = getattr(self, "_artifact_tmux_pane_id", None)
        if pane_id is None:
            return False
        if not is_tmux_session():
            self._clear_tracked_artifact_tmux_pane_state(notify_warnings=False)
            return False
        if not artifact_tmux_pane_exists(pane_id):
            self._clear_tracked_artifact_tmux_pane_state(notify_warnings=False)
            return False
        return True

    def _sync_artifact_viewer_layout(self) -> None:
        """Keep the Agents side panel collapsed while a tracked pane is live."""
        self._set_artifact_viewer_layout_collapsed(self._artifact_tmux_pane_visible())

    def _guard_agent_navigation_for_artifact_viewer(self) -> bool:
        """Block row-changing Agents navigation while an artifact pane is live."""
        if getattr(self, "current_tab", "agents") != "agents":
            return False
        if not self._artifact_tmux_pane_visible():
            return False
        self.notify(ARTIFACT_VIEWER_NAV_MESSAGE, severity="warning")  # type: ignore[attr-defined]
        return True

    def _focus_tracked_artifact_tmux_pane(self) -> bool:
        """Focus the tracked artifact pane when the Agents artifact split is live."""
        if getattr(self, "current_tab", "agents") != "agents":
            return False
        if not self._artifact_tmux_pane_visible():
            return False

        from ...graphics import select_tmux_pane

        pane_id = getattr(self, "_artifact_tmux_pane_id", None)
        if pane_id is None:
            return False
        result = select_tmux_pane(pane_id)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]
            self._sync_artifact_viewer_layout()
        return True

    def _list_selected_agent_artifacts(self, agent: Agent | None) -> list[Any]:
        """Return artifact entries available for *agent* without UI side effects."""
        if agent is None:
            return []
        from ...provider_contract import SelectionGeneration
        from ._artifact_provider import read_agent_artifacts_for_tui

        generation = getattr(self, "_agent_artifact_selection_generation", None)
        if generation is None:
            generation = SelectionGeneration()
            self._agent_artifact_selection_generation = generation  # type: ignore[attr-defined]
        cache: dict[tuple[Any, ...], list[Any]] = getattr(
            self, "_agent_artifact_page_cache", {}
        )
        if not hasattr(self, "_agent_artifact_page_cache"):
            self._agent_artifact_page_cache = cache  # type: ignore[attr-defined]

        identity = getattr(agent, "identity", None)
        if identity is None:
            artifacts_dir = agent.get_artifacts_dir()
            if artifacts_dir is None:
                return []
            from sase.core.agent_artifact_facade import list_agent_artifacts

            try:
                return list_agent_artifacts(artifacts_dir)
            except Exception:
                return []

        row_key = self._agent_artifact_cache_key(agent, identity)
        cached = cache.get(row_key)
        if cached is not None:
            return list(cached)
        generation.bump()
        try:
            result = read_agent_artifacts_for_tui(
                agent,
                selection_generation=generation,
                client=getattr(self, "_daemon_read_client", None),
                args=getattr(self, "_daemon_read_args", None),
            )
        except Exception:
            return []
        page = result.value
        request = getattr(page, "request", None)
        if request is not None and not generation.accepts(request):
            return []
        artifacts = list(page.artifacts)
        cache[row_key] = artifacts
        self._agent_artifact_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._agent_artifact_provider_snapshot = page.shared_snapshot  # type: ignore[attr-defined]
        return artifacts

    def _agent_artifact_cache_key(
        self,
        agent: Agent,
        identity: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        """Return cache key state that changes when row artifacts can change."""
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

    def _open_agent_artifact(self, artifact: Any) -> None:
        from ...graphics import (
            is_tmux_session,
            view_agent_artifact,
            view_agent_artifact_in_tmux_pane,
        )

        if is_tmux_session():
            result = self._with_artifact_viewer_notify_pid(
                lambda: view_agent_artifact_in_tmux_pane(artifact)
            )
            if result.ok and result.pane_id is not None:
                self._track_artifact_tmux_pane(result.pane_id)
        else:
            with self.suspend():  # type: ignore[attr-defined]
                result = view_agent_artifact(artifact)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _open_agent_artifacts(self, artifacts: list[Any]) -> None:
        if not artifacts:
            return
        if len(artifacts) == 1:
            self._open_agent_artifact(artifacts[0])
            return

        from ...graphics import (
            is_tmux_session,
            view_agent_artifacts,
            view_agent_artifacts_in_tmux_pane,
        )

        if is_tmux_session():
            result = self._with_artifact_viewer_notify_pid(
                lambda: view_agent_artifacts_in_tmux_pane(artifacts)
            )
            if result.ok and result.pane_id is not None:
                self._track_artifact_tmux_pane(result.pane_id)
        else:
            with self.suspend():  # type: ignore[attr-defined]
                result = view_agent_artifacts(artifacts)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

    def _toggle_tracked_artifact_tmux_pane(self) -> bool:
        """Close a live tracked artifact pane, returning whether the action is done."""
        from ...graphics import (
            artifact_tmux_pane_exists,
            close_artifact_tmux_pane,
            is_tmux_session,
        )

        if not is_tmux_session():
            return False

        pane_id = getattr(self, "_artifact_tmux_pane_id", None)
        if pane_id is None:
            return False
        if not artifact_tmux_pane_exists(pane_id):
            self._clear_tracked_artifact_tmux_pane_state(notify_warnings=False)
            return False

        self._restore_artifact_tmux_decoration(notify_warnings=True)
        result = close_artifact_tmux_pane(pane_id)
        self._artifact_tmux_pane_id = None  # type: ignore[attr-defined]
        self._set_artifact_viewer_layout_collapsed(False)
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

    def _agent_artifact_prefix_label(self, agent: Agent) -> str:
        """Return a short, human-readable prefix to identify *agent* in the picker."""
        name = agent.display_name or ""
        agent_name = getattr(agent, "agent_name", None) or ""
        if agent_name and agent_name != name:
            return f"{name} @{agent_name}" if name else f"@{agent_name}"
        return name

    def _collect_marked_agent_artifacts(
        self,
    ) -> tuple[list[Any], list[str | None], int]:
        """Return artifacts, per-row agent labels, and marked-agent count."""
        marked: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        artifacts: list[Any] = []
        labels: list[str | None] = []
        for agent in marked:
            agent_label = self._agent_artifact_prefix_label(agent)
            for artifact in self._list_selected_agent_artifacts(agent):
                artifacts.append(artifact)
                labels.append(agent_label)
        return artifacts, labels, len(marked)

    def action_open_agent_artifacts(self) -> None:
        """Open or choose artifacts associated with the selected agent."""
        if self.current_tab != "agents":
            return
        if self._toggle_tracked_artifact_tmux_pane():
            return

        from ...modals import AgentArtifactSelectionModal

        def _open_selected(selection: Any) -> None:
            try:
                selected_artifacts = self._normalize_agent_artifact_selection(selection)
                if selected_artifacts:
                    self._open_agent_artifacts(selected_artifacts)
            finally:
                self._focus_agent_list_after_artifact_modal()

        if self._marked_agents:
            artifacts, labels, marked_count = self._collect_marked_agent_artifacts()
            if marked_count == 0:
                self.notify(  # type: ignore[attr-defined]
                    "No marked agents remain",
                    severity="warning",
                )
                return
            if not artifacts:
                self.notify(  # type: ignore[attr-defined]
                    "No artifacts found in marked agents",
                    severity="warning",
                )
                return
            self.push_screen(  # type: ignore[attr-defined]
                AgentArtifactSelectionModal(
                    artifacts,
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

        artifacts = self._list_selected_agent_artifacts(agent)
        if not artifacts:
            message = (
                "No completed artifacts for this agent"
                if agent.status not in ("DONE", "FAILED")
                else "No artifacts found"
            )
            self.notify(message, severity="warning")  # type: ignore[attr-defined]
            return

        self.push_screen(AgentArtifactSelectionModal(artifacts), _open_selected)  # type: ignore[attr-defined]

    def _normalize_agent_artifact_selection(self, selection: Any) -> list[Any]:
        if selection is None:
            return []
        if isinstance(selection, list):
            return selection
        return [selection]

    def action_view_image(self) -> None:
        """Compatibility wrapper for older keymaps."""
        self.action_open_agent_artifacts()

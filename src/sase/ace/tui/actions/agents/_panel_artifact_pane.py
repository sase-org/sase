"""Artifact-file viewer tmux pane tracking and Agents-tab layout state."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from types import FrameType
from typing import TYPE_CHECKING, Any

from ._panel_types import (
    ARTIFACT_FILE_NOTIFY_PID_ENV,
    ARTIFACT_FILE_VIEWER_LAYOUT_CLASS,
    ARTIFACT_FILE_VIEWER_NAV_MESSAGE,
    TabName,
)

if TYPE_CHECKING:
    from ...graphics import ArtifactFileViewerResult, TmuxPaneDecorationState


class AgentArtifactFilePaneMixin:
    """Mixin tracking the artifact-file tmux pane and its layout side effects."""

    current_tab: TabName
    _artifact_file_tmux_pane_id: str | None
    _artifact_file_tmux_decoration_state: TmuxPaneDecorationState | None
    _artifact_file_viewer_previous_sigusr1_handler: (
        signal.Handlers | int | Callable[[int, FrameType | None], Any] | None
    )

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

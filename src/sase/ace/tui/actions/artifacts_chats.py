"""App actions for the Artifacts Chats pane scaffold."""

from __future__ import annotations

from ..widgets.artifacts.chats_pane import ArtifactsChatsPane


CHATS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "chats_next",
        "chats_prev",
        "chats_view_selected",
        "chats_filters",
        "chats_cycle_provenance",
        "chats_open_agent",
        "chats_open_external",
        "chats_copy_path",
        "chats_refresh",
    }
)


class ArtifactsChatsActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` for the Chats pane."""

    def _chats_pane(self) -> ArtifactsChatsPane | None:
        try:
            return self.query_one("#artifacts-chats-pane", ArtifactsChatsPane)  # type: ignore[attr-defined]
        except Exception:
            return None

    def action_chats_next(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
            try:
                pane.move_selection(1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_chats_prev(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
            try:
                pane.move_selection(-1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_chats_view_selected(self) -> None:
        """Open the selected chat once catalog-backed rows are available."""

    def action_chats_filters(self) -> None:
        """Open chat filters once the filter session is implemented."""

    def action_chats_cycle_provenance(self) -> None:
        """Cycle sync provenance once the catalog is implemented."""

    def action_chats_open_agent(self) -> None:
        """Open the associated agent once chat-to-agent links are available."""

    def action_chats_open_external(self) -> None:
        """Open the selected transcript once chat rows are available."""

    def action_chats_copy_path(self) -> None:
        """Copy the selected transcript path once chat rows are available."""

    def action_chats_refresh(self) -> None:
        pane = self._chats_pane()
        if pane is not None:
            pane.request_refresh()


__all__ = ["ArtifactsChatsActionsMixin", "CHATS_ARTIFACT_ACTIONS"]

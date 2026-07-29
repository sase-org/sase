"""App action stubs for the Artifacts Files pane scaffold."""

from __future__ import annotations

from ..widgets.artifacts.files_pane import ArtifactsFilesPane


FILES_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "files_next",
        "files_prev",
        "files_view_selected",
        "files_open_viewer",
        "files_open_external",
        "files_open_agent",
        "files_filters",
        "files_cycle_kind",
        "files_copy_reference",
        "files_copy_path",
        "files_refresh",
    }
)


class ArtifactsFilesActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` for the Files pane."""

    def _files_pane(self) -> ArtifactsFilesPane | None:
        try:
            return self.query_one("#artifacts-files-pane", ArtifactsFilesPane)  # type: ignore[attr-defined]
        except Exception:
            return None

    def action_files_next(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.move_selection(1)

    def action_files_prev(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.move_selection(-1)

    def action_files_view_selected(self) -> None:
        return

    def action_files_open_viewer(self) -> None:
        return

    def action_files_open_external(self) -> None:
        return

    def action_files_open_agent(self) -> None:
        return

    def action_files_filters(self) -> None:
        return

    def action_files_cycle_kind(self) -> None:
        return

    def action_files_copy_reference(self) -> None:
        return

    def action_files_copy_path(self) -> None:
        return

    def action_files_refresh(self) -> None:
        pane = self._files_pane()
        if pane is not None:
            pane.request_refresh()


__all__ = ["ArtifactsFilesActionsMixin", "FILES_ARTIFACT_ACTIONS"]

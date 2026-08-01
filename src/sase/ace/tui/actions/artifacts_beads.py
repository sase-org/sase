"""App actions for the read-only Artifacts Beads pane."""

from __future__ import annotations

from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane


BEADS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "beads_next",
        "beads_prev",
        "beads_view_selected",
        "beads_filters",
        "beads_expand",
        "beads_collapse",
        "beads_cycle_status",
        "beads_edit",
        "beads_add_note",
        "beads_create",
        "beads_close",
        "beads_launch_work",
        "beads_open_bug",
        "beads_open_plan",
        "beads_refresh",
    }
)


class ArtifactsBeadsActionsMixin:
    """Read-only actions plus inert mutation stubs for the Beads pane."""

    def _beads_pane(self) -> ArtifactsBeadsPane | None:
        try:
            return self.query_one(  # type: ignore[attr-defined]
                "#artifacts-beads-pane", ArtifactsBeadsPane
            )
        except Exception:
            return None

    def action_beads_next(self) -> None:
        pane = self._beads_pane()
        if pane is None:
            return
        self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
        try:
            pane.move_selection(1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_beads_prev(self) -> None:
        pane = self._beads_pane()
        if pane is None:
            return
        self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
        try:
            pane.move_selection(-1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_beads_view_selected(self) -> None:
        pane = self._beads_pane()
        payload = None if pane is None else pane.selected_preview()
        if payload is None:
            return
        from ..modals.preview_panel_modal import PreviewPanelModal

        self.push_screen(PreviewPanelModal(payload))  # type: ignore[attr-defined]

    def action_beads_filters(self) -> None:
        # The mounted slot becomes interactive in the filtering phase.
        self._beads_pane()

    def action_beads_expand(self) -> None:
        pane = self._beads_pane()
        if pane is not None:
            pane.set_selected_epic_expanded(True)

    def action_beads_collapse(self) -> None:
        pane = self._beads_pane()
        if pane is not None:
            pane.set_selected_epic_expanded(False)

    def action_beads_cycle_status(self) -> None:
        self._beads_pane()

    def action_beads_edit(self) -> None:
        self._beads_pane()

    def action_beads_add_note(self) -> None:
        self._beads_pane()

    def action_beads_create(self) -> None:
        self._beads_pane()

    def action_beads_close(self) -> None:
        self._beads_pane()

    def action_beads_launch_work(self) -> None:
        self._beads_pane()

    def action_beads_open_bug(self) -> None:
        self._beads_pane()

    def action_beads_open_plan(self) -> None:
        self._beads_pane()

    def action_beads_refresh(self) -> None:
        pane = self._beads_pane()
        if pane is not None:
            pane.request_refresh()


__all__ = ["ArtifactsBeadsActionsMixin", "BEADS_ARTIFACT_ACTIONS"]

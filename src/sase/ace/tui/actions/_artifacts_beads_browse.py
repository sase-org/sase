"""Browsing actions for the Artifacts Beads pane."""

from __future__ import annotations

from sase.bead.model import Status

from ._artifacts_beads_common import ArtifactsBeadsCommonMixin


class ArtifactsBeadsBrowseActionsMixin(ArtifactsBeadsCommonMixin):
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
        if (pane := self._beads_pane()) is not None:
            show_filters = getattr(pane, "show_filters", None)
            if callable(show_filters):
                show_filters()

    def action_beads_expand(self) -> None:
        if (pane := self._beads_pane()) is not None:
            pane.set_selected_epic_expanded(True)

    def action_beads_collapse(self) -> None:
        if (pane := self._beads_pane()) is not None:
            pane.set_selected_epic_expanded(False)

    def action_beads_open_plan(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        snapshot = pane.snapshot
        plan_path = (
            ""
            if snapshot is None
            else snapshot.plan_links.get((row.project, row.issue.id), "")
        )
        if not plan_path:
            self.notify(  # type: ignore[attr-defined]
                "This bead links no plan file", severity="warning"
            )
            return
        plan_kind = "archive" if row.issue.status is Status.CLOSED else "active"
        self._request_artifacts_entry(  # type: ignore[attr-defined]
            "ref:plan",
            ("plan", row.project, plan_kind, plan_path),
        )

    def action_beads_refresh(self) -> None:
        if (pane := self._beads_pane()) is not None:
            pane.request_refresh()

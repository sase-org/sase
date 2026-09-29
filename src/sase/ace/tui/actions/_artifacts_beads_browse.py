"""Browsing actions for the Artifacts Beads pane."""

from __future__ import annotations

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

    def action_beads_open_attachments(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        _pane, row = selected
        from ..graphics import ArtifactFileViewSpec, artifact_file_view_mode
        from ..graphics import view_artifact_files
        from ..util.external_tool import suspend_for_external_tool
        from ..widgets.artifacts.beads_attachment_views import (
            cached_attachment_view_paths,
        )

        paths = cached_attachment_view_paths(row.issue)
        if not paths:
            self._notify_beads(
                "No cached attachments on this bead — fetch or attach files first",
                severity="warning",
            )
            return
        specs: list[ArtifactFileViewSpec] = []
        for path in paths:
            mode: str
            try:
                mode = str(artifact_file_view_mode(path))
            except Exception:
                mode = "file"
            kind: str = mode if mode in {"image", "video", "pdf"} else "file"
            specs.append(ArtifactFileViewSpec(path, kind=kind))
        with suspend_for_external_tool(
            self,
            action="beads_open_attachments",
            tool_kind="viewer",
            path_count=len(specs),
        ):
            result = view_artifact_files(specs)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")  # type: ignore[attr-defined]

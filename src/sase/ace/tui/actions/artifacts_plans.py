"""App actions for the document-only Artifacts Plans pane."""

from __future__ import annotations

from typing import cast

from sase.bead.model import IssueType

from ..widgets.artifacts.bead_plan_links import BeadPlanLink
from ..widgets.artifacts.plans_pane import ArtifactsDocumentsPane, ArtifactsPlansPane

PLANS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "plans_next",
        "plans_prev",
        "plans_view_selected",
        "plans_filters",
        "plans_approve",
        "plans_reject",
        "plans_open_bead",
        "plans_refresh",
    }
)


class ArtifactsPlansActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` without expanding app.py."""

    def _plans_pane(self) -> ArtifactsPlansPane | None:
        try:
            return self.query_one("#artifacts-plans-pane", ArtifactsPlansPane)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _active_documents_pane(self) -> ArtifactsDocumentsPane | None:
        pane_key = getattr(self, "current_artifacts_pane_key", "ref:plan")
        if not isinstance(pane_key, str) or not pane_key.startswith("ref:"):
            return None
        view = getattr(self, "_artifacts_view", lambda: None)()
        if view is None:
            return self._plans_pane()
        try:
            return cast(ArtifactsDocumentsPane, view.entry_navigator(pane_key))
        except Exception:
            return None

    def action_plans_next(self) -> None:
        pane = self._active_documents_pane()
        if pane is not None:
            self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
            try:
                pane.move_selection(1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_plans_prev(self) -> None:
        pane = self._active_documents_pane()
        if pane is not None:
            self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
            try:
                pane.move_selection(-1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_plans_filters(self) -> None:
        if (pane := self._active_documents_pane()) is not None:
            pane.show_filters()

    def action_plans_view_selected(self) -> None:
        pane = self._active_documents_pane()
        payload = None if pane is None else pane.selected_preview()
        if payload is None:
            return
        from ..modals.preview_panel_modal import PreviewPanelModal

        self.push_screen(PreviewPanelModal(payload))  # type: ignore[attr-defined]

    def action_plans_refresh(self) -> None:
        if (pane := self._active_documents_pane()) is not None:
            pane.request_refresh()

    def action_plans_open_bead(self) -> None:
        pane = self._active_documents_pane()
        if pane is not None and pane.provider_kind != "plan":
            self.notify(  # type: ignore[attr-defined]
                "Linked bead navigation is only available for plans",
                severity="warning",
            )
            return
        row = None if pane is None else pane.selected_row()
        link = None if row is None else row.bead_link
        if link is None:
            self.notify("No bead links this plan file", severity="warning")  # type: ignore[attr-defined]
            return
        self._request_artifacts_entry(  # type: ignore[attr-defined]
            "beads",
            ("bead", link.project, _bead_row_kind(link), link.bead_id),
        )

    def action_plans_approve(self) -> None:
        self._open_selected_plan_approval(intent="approve")

    def action_plans_reject(self) -> None:
        self._open_selected_plan_approval(intent="reject")

    def _open_selected_plan_approval(self, *, intent: str) -> None:
        pane = self._active_documents_pane()
        if pane is not None and pane.provider_kind != "plan":
            self.notify(  # type: ignore[attr-defined]
                "Plan proposal approval is only available for plans",
                severity="warning",
            )
            return
        row = None if pane is None else pane.selected_row()
        if row is None or row.proposal is None:
            self.notify("Select a pending plan proposal first", severity="warning")  # type: ignore[attr-defined]
            return
        from .agents._notification_modals import handle_plan_approval

        opened = handle_plan_approval(self, row.proposal.notification)
        if opened and intent == "reject":
            self.notify("Review the plan, then press r to confirm rejection")  # type: ignore[attr-defined]


def _bead_row_kind(link: BeadPlanLink) -> str:
    if link.bead_type is IssueType.TASK:
        return "task"
    if link.bead_type is IssueType.PHASE:
        return "phase"
    return "epic"


__all__ = ["ArtifactsPlansActionsMixin", "PLANS_ARTIFACT_ACTIONS"]

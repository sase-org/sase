"""App-level actions for the Artifacts Commits pane."""

from __future__ import annotations

from typing import Any

from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts import CommitsPane


COMMITS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "commits_next",
        "commits_prev",
        "commits_view_selected",
        "commits_copy_sha",
        "commits_filters",
        "commits_toggle_sdd",
        "commits_cycle_merges",
        "commits_toggle_all_projects",
        "commits_fetch",
        "commits_refresh",
    }
)


class ArtifactsCommitsActionsMixin:
    """Registry-driven actions scoped to the Commits sub-tab."""

    current_tab: Any
    current_artifacts_subtab: str

    def _commits_pane(self) -> CommitsPane | None:
        try:
            return self.query_one("#artifacts-commits-pane", CommitsPane)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None

    def _commits_active(self) -> bool:
        return (
            self.current_tab == ARTIFACTS_TAB
            and self.current_artifacts_subtab == "commits"
        )

    def action_commits_next(self) -> None:
        pane = self._commits_pane()
        if not self._commits_active() or pane is None:
            return
        self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
        try:
            pane.move_selection(1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_commits_prev(self) -> None:
        pane = self._commits_pane()
        if not self._commits_active() or pane is None:
            return
        self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
        try:
            pane.move_selection(-1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_commits_view_selected(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.open_selected_commit()

    def action_commits_copy_sha(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.copy_selected_sha()

    def action_commits_filters(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.show_filters()

    def action_commits_toggle_sdd(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.toggle_sdd()

    def action_commits_cycle_merges(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.cycle_merges()

    def action_commits_toggle_all_projects(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.toggle_all_projects()

    def action_commits_fetch(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.fetch_commits()

    def action_commits_refresh(self) -> None:
        pane = self._commits_pane()
        if self._commits_active() and pane is not None:
            pane.refresh_commits()


__all__ = ["ArtifactsCommitsActionsMixin", "COMMITS_ARTIFACT_ACTIONS"]

"""Query-edit actions for sase's TUI app."""

from __future__ import annotations

from ._base_types import BaseActionsHost


class BaseQueryActionsMixin(BaseActionsHost):
    """Mixin providing search-query edit actions."""

    def action_edit_query(self) -> None:
        """Edit the search query.

        On Agents and Artifacts entry panes, delegates to inline filters.

        Supports saving queries with # prefix:
        - #<N> <query> - Save query to slot N (0-9)
        - # <query> - Save query to next available slot
        - #<N> (no query) - Delete query from slot N
        """
        if self.current_tab == "agents":
            self._edit_agent_search_query()  # type: ignore[attr-defined]
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "patches"
        ):
            pane = self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
            show_filters = getattr(pane, "show_filters", None)
            if callable(show_filters):
                show_filters()
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "stitches"
        ):
            pane = self._commits_pane()  # type: ignore[attr-defined]
            if pane is not None:
                pane.show_filters()
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "agents"
        ):
            pane = self._artifacts_entry_navigator("agents")  # type: ignore[attr-defined]
            show_filters = getattr(pane, "show_filters", None)
            if callable(show_filters):
                show_filters()
            return
        if self.current_tab == "artifacts":
            from ..artifact_tabs import PaneCapability, artifacts_pane_contract

            pane_key = str(getattr(self, "current_artifacts_pane_key", "patches"))
            contract = getattr(self, "active_artifacts_contract", None) or (
                artifacts_pane_contract(pane_key)
            )
            if (
                contract is not None
                and contract.is_document_provider()
                and contract.has(PaneCapability.FILTER_SESSION)
            ):
                pane = self._active_documents_pane()  # type: ignore[attr-defined]
                if pane is not None:
                    pane.show_filters()
                return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "beads"
        ):
            pane = self._beads_pane()  # type: ignore[attr-defined]
            if pane is not None:
                pane.show_filters()
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "files"
        ):
            pane = self._files_pane()  # type: ignore[attr-defined]
            if pane is not None:
                pane.show_filters()
            return

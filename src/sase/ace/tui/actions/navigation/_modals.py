"""Modal navigation actions for the ace TUI app."""

from __future__ import annotations

from ...tab_order import ARTIFACTS_TAB
from ._types import NavigationMixinBase


class NavigationModalMixin(NavigationMixinBase):
    """Mixin providing cross-tab jump and help modal actions."""

    # --- Jump To All Entries (cross-tab) ---

    def action_jump_to_all_entries(self) -> None:
        """Open the cross-tab jump modal showing entries from all tabs."""
        from ...modals import JumpAllModal, JumpAllResult

        # Capture current position before opening modal
        pre_jump_position = JumpAllResult(
            tab=self.current_tab,  # type: ignore[arg-type]
            index=self.current_idx,
        )

        def _on_dismiss(result: JumpAllResult | None) -> None:
            if result is None:
                return
            self._jump_all_last_position = pre_jump_position
            self._save_current_tab_position()  # type: ignore[attr-defined]
            if result.tab == ARTIFACTS_TAB:
                # The modal only lists Patch entries under the
                # Artifacts tab, so PRs is unconditionally the right pane.
                from ...artifact_tabs import switch_to_artifacts_subtab

                switch_to_artifacts_subtab(self, "patches")
            elif result.tab in {
                "patches",
                "changespecs",  # legacy compatibility alias
            }:
                self.current_artifacts_subtab = "patches"  # type: ignore[attr-defined]
                self.current_tab = result.tab  # type: ignore[assignment]
            else:
                self.current_tab = result.tab  # type: ignore[assignment]
            self.current_idx = result.index

        patches = getattr(
            self,
            "patches",
            getattr(self, "changespecs", []),  # legacy compatibility alias
        )
        self.push_screen(  # type: ignore[attr-defined]
            JumpAllModal(
                patches=patches,
                agents=self._agents,
                axe_items=self._axe_items,
                last_position=self._jump_all_last_position,
            ),
            _on_dismiss,
        )

    # --- Help Action ---

    def action_show_help(self) -> None:
        """Show the help modal with all keybindings."""
        from ...modals import HelpModal

        if self.current_tab == "agents":
            self._prepare_agents_help_guide_state()

        pane_id = getattr(self, "current_artifacts_pane_key", "patches")
        query_context = getattr(self, "_query_history_help_context", None)
        if callable(query_context):
            active_query, query_history, query_history_enabled = query_context()
        else:
            active_query = self.canonical_query_string  # type: ignore[attr-defined]
            query_history = None
            query_history_enabled = False
        self.push_screen(  # type: ignore[attr-defined]
            HelpModal(
                current_tab=self.current_tab,
                active_query=active_query,
                registry=self._keymap_registry,
                saved_queries={
                    slot: record.canonical
                    for slot, record in self._saved_queries.get(pane_id, {}).items()
                },
                query_history=query_history,
                query_history_enabled=query_history_enabled,
                pane_id=pane_id,
                agents_launch_targets_available=getattr(
                    self,
                    "_agents_onboarding_launch_targets_available",
                    False,
                ),
                agents_plugins_installed=getattr(
                    self,
                    "_agents_onboarding_plugins_installed",
                    True,
                ),
            )
        )

    def _prepare_agents_help_guide_state(self) -> None:
        """Schedule the background state refresh used by the Agents guide."""
        schedule_launch_targets = getattr(
            self,
            "_schedule_agents_onboarding_launch_targets_refresh",
            None,
        )
        if callable(schedule_launch_targets):
            schedule_launch_targets()
        schedule_plugins = getattr(
            self,
            "_schedule_agents_onboarding_plugins_refresh",
            None,
        )
        if callable(schedule_plugins):
            schedule_plugins()

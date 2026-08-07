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
                # The modal only lists ChangeSpec entries under the
                # Artifacts tab, so PRs is unconditionally the right pane.
                from ...artifact_tabs import switch_to_artifacts_subtab

                switch_to_artifacts_subtab(self, "prs")
            else:
                self.current_tab = result.tab  # type: ignore[assignment]
            self.current_idx = result.index

        self.push_screen(  # type: ignore[attr-defined]
            JumpAllModal(
                changespecs=self.changespecs,
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

        self.push_screen(  # type: ignore[attr-defined]
            HelpModal(
                current_tab=self.current_tab,
                active_query=self.canonical_query_string,  # type: ignore[attr-defined]
                registry=self._keymap_registry,
                saved_queries=dict(self._saved_queries),
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

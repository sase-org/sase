"""Modal navigation actions for the ace TUI app."""

from __future__ import annotations

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

        self.push_screen(  # type: ignore[attr-defined]
            HelpModal(
                current_tab=self.current_tab,
                active_query=self.canonical_query_string,  # type: ignore[attr-defined]
            )
        )

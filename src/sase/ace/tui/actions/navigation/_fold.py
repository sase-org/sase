"""Fold-mode navigation actions for the ace TUI app."""

from __future__ import annotations

from ...models.fold_state import (
    FoldLevel,
    cycle_deltas_fold_level,
    cycle_forward,
)
from ._types import NavigationMixinBase


class FoldNavigationMixin(NavigationMixinBase):
    """Mixin providing fold mode actions."""

    # --- Fold Mode Actions ---

    def action_start_fold_mode(self) -> None:
        """Enter fold mode - waiting for sub-key (c/h/z)."""
        self._fold_mode_active = True
        self._update_fold_footer()

    def _handle_fold_key(self, key: str) -> bool:
        """Handle fold sub-key. Returns True if handled."""
        if not self._fold_mode_active:
            return False

        self._fold_mode_active = False
        fold_keys = self._keymap_registry.fold_mode.keys

        if key == "escape":
            # Cancel silently and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == fold_keys["cycle_commits"]:
            self.commits_collapsed = cycle_forward(self.commits_collapsed)
        elif key == fold_keys["cycle_hooks"]:
            self.hooks_collapsed = cycle_forward(self.hooks_collapsed)
        elif key == fold_keys["cycle_mentors"]:
            self.mentors_collapsed = cycle_forward(self.mentors_collapsed)
        elif key == fold_keys["cycle_timestamps"]:
            self.timestamps_collapsed = cycle_forward(self.timestamps_collapsed)
        elif key == fold_keys["cycle_deltas"]:
            self.deltas_collapsed = cycle_deltas_fold_level(self.deltas_collapsed)
        elif key == fold_keys["toggle_commits"]:
            self.commits_collapsed = (
                FoldLevel.FULLY_EXPANDED
                if self.commits_collapsed == FoldLevel.COLLAPSED
                else FoldLevel.COLLAPSED
            )
        elif key == fold_keys["toggle_hooks"]:
            self.hooks_collapsed = (
                FoldLevel.FULLY_EXPANDED
                if self.hooks_collapsed == FoldLevel.COLLAPSED
                else FoldLevel.COLLAPSED
            )
        elif key == fold_keys["toggle_mentors"]:
            self.mentors_collapsed = (
                FoldLevel.FULLY_EXPANDED
                if self.mentors_collapsed == FoldLevel.COLLAPSED
                else FoldLevel.COLLAPSED
            )
        elif key == fold_keys["toggle_timestamps"]:
            self.timestamps_collapsed = (
                FoldLevel.FULLY_EXPANDED
                if self.timestamps_collapsed == FoldLevel.COLLAPSED
                else FoldLevel.COLLAPSED
            )
        elif key == fold_keys["toggle_deltas"]:
            self.deltas_collapsed = (
                FoldLevel.FULLY_EXPANDED
                if self.deltas_collapsed == FoldLevel.COLLAPSED
                else FoldLevel.COLLAPSED
            )
        elif key == fold_keys["cycle_all"]:
            # Cycle all - if all at same level, cycle forward; otherwise collapse all
            if self._all_fold_states_aligned():
                new_state = cycle_forward(self.commits_collapsed)
            else:
                new_state = FoldLevel.COLLAPSED
            self.commits_collapsed = new_state
            self.hooks_collapsed = new_state
            self.mentors_collapsed = new_state
            self.timestamps_collapsed = new_state
            self.deltas_collapsed = new_state
        elif key == fold_keys["toggle_all"]:
            # Toggle: if not fully collapsed, collapse all; otherwise fully expand
            all_collapsed = (
                self.commits_collapsed
                == self.hooks_collapsed
                == self.mentors_collapsed
                == self.timestamps_collapsed
                == self.deltas_collapsed
                == FoldLevel.COLLAPSED
            )
            new_state = (
                FoldLevel.FULLY_EXPANDED if all_collapsed else FoldLevel.COLLAPSED
            )
            self.commits_collapsed = new_state
            self.hooks_collapsed = new_state
            self.mentors_collapsed = new_state
            self.timestamps_collapsed = new_state
            self.deltas_collapsed = new_state
        else:
            # Invalid key - cancel fold mode and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        self._refresh_current_tab()  # type: ignore[attr-defined]
        self._update_fold_tab_indicator()
        return True

    def _all_fold_states_aligned(self) -> bool:
        """Return whether all section folds are aligned."""
        shared_state = self.commits_collapsed
        return (
            shared_state
            == self.hooks_collapsed
            == self.mentors_collapsed
            == self.timestamps_collapsed
            == self.deltas_collapsed
        )

    def _update_fold_footer(self) -> None:
        """Update the footer to show fold mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_fold_bindings()
        except Exception:
            pass

    def _update_fold_tab_indicator(self) -> None:
        """Push current fold states to the info panel indicator."""
        from ...widgets import ChangeSpecInfoPanel

        try:
            info_panel = self.query_one("#info-panel", ChangeSpecInfoPanel)  # type: ignore[attr-defined]
            info_panel.update_fold_states(
                self.commits_collapsed,
                self.hooks_collapsed,
                self.mentors_collapsed,
                self.timestamps_collapsed,
                self.deltas_collapsed,
            )
        except Exception:
            pass

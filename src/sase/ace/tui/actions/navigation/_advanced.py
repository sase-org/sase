"""Advanced navigation mixin for fold mode, help modal, and history navigation."""

from __future__ import annotations

from ...changespec_history import ChangeSpecHistoryEntry
from ...models.fold_state import FoldLevel, cycle_forward
from .jump_hints import build_jump_hint_maps
from ._types import NavigationMixinBase


class AdvancedNavigationMixin(NavigationMixinBase):
    """Mixin providing fold mode, help modal, and history navigation."""

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
        elif key == fold_keys["cycle_all"]:
            # Cycle all - if all at same level, cycle forward; otherwise collapse all
            if (
                self.commits_collapsed
                == self.hooks_collapsed
                == self.mentors_collapsed
                == self.timestamps_collapsed
            ):
                new_state = cycle_forward(self.commits_collapsed)
            else:
                new_state = FoldLevel.COLLAPSED
            self.commits_collapsed = new_state
            self.hooks_collapsed = new_state
            self.mentors_collapsed = new_state
            self.timestamps_collapsed = new_state
        elif key == fold_keys["toggle_all"]:
            # Toggle: if not fully collapsed, collapse all; otherwise fully expand
            all_collapsed = (
                self.commits_collapsed
                == self.hooks_collapsed
                == self.mentors_collapsed
                == self.timestamps_collapsed
                == FoldLevel.COLLAPSED
            )
            new_state = (
                FoldLevel.FULLY_EXPANDED if all_collapsed else FoldLevel.COLLAPSED
            )
            self.commits_collapsed = new_state
            self.hooks_collapsed = new_state
            self.mentors_collapsed = new_state
            self.timestamps_collapsed = new_state
        else:
            # Invalid key - cancel fold mode and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        self._refresh_current_tab()  # type: ignore[attr-defined]
        self._update_fold_tab_indicator()
        return True

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
            )
        except Exception:
            pass

    # --- Jump To Entry ---

    def action_jump_to_entry(self) -> None:
        """Enter one-key jump mode for the current tab's left-panel entries."""
        indices = self._jump_candidate_indices()
        if not indices:
            return
        self._entry_jump_hint_to_index, self._entry_jump_index_to_hint = (
            build_jump_hint_maps(indices)
        )
        if not self._entry_jump_hint_to_index:
            return
        self._entry_jump_mode_active = True
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _jump_candidate_indices(self) -> list[int]:
        """Return target indices for jump mode in visual order."""
        if self.current_tab == "changespecs":
            return list(range(len(self.changespecs)))
        if self.current_tab == "agents":
            return [*self._main_panel_indices, *self._pinned_panel_indices]
        return list(range(len(self._axe_items)))  # type: ignore[attr-defined]

    def _exit_entry_jump_mode(self) -> None:
        """Clear jump mode state and remove hint overlays."""
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _handle_entry_jump_key(self, key: str) -> bool:
        """Handle one keypress while jump mode is active."""
        if not self._entry_jump_mode_active:
            return False
        if key == "escape":
            self._exit_entry_jump_mode()
            return True

        target = self._entry_jump_hint_to_index.get(key)
        if target is None:
            self._exit_entry_jump_mode()
            return True

        if self.current_tab == "agents":
            if target in self._pinned_panel_idx_map:
                self._pinned_panel_focused = "pinned"
            elif target in self._main_panel_idx_map:
                self._pinned_panel_focused = "main"
            self.current_idx = target
            self._entry_jump_mode_active = False
            self._entry_jump_hint_to_index = {}
            self._entry_jump_index_to_hint = {}
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
            return True

        self.current_idx = target
        self._exit_entry_jump_mode()
        return True

    # --- Jump To All Entries (cross-tab) ---

    def action_jump_to_all_entries(self) -> None:
        """Open the cross-tab jump modal showing entries from all tabs."""
        from ...modals import JumpAllModal, JumpAllResult

        def _on_dismiss(result: JumpAllResult | None) -> None:
            if result is None:
                return
            self._save_current_tab_position()  # type: ignore[attr-defined]
            self.current_tab = result.tab  # type: ignore[assignment]
            if result.tab == "agents" and result.pinned_panel_focused is not None:
                self._pinned_panel_focused = result.pinned_panel_focused
            self.current_idx = result.index

        self.push_screen(  # type: ignore[attr-defined]
            JumpAllModal(
                changespecs=self.changespecs,
                agents=self._agents,
                main_panel_indices=self._main_panel_indices,
                pinned_panel_indices=self._pinned_panel_indices,
                pinned_panel_idx_map=self._pinned_panel_idx_map,
                axe_items=self._axe_items,
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

    # --- ChangeSpec History Navigation (ctrl+o / ctrl+k) ---

    def _get_current_changespec_history_entry(
        self,
    ) -> ChangeSpecHistoryEntry | None:
        """Create a history entry for the current ChangeSpec.

        Returns:
            ChangeSpecHistoryEntry for the current CL, or None if no CLs.
        """
        from ...changespec_history import ChangeSpecHistoryEntry

        if not self.changespecs or self.current_idx >= len(self.changespecs):
            return None

        cs = self.changespecs[self.current_idx]
        return ChangeSpecHistoryEntry(
            name=cs.name,
            file_path=cs.file_path,
            query=self.canonical_query_string,  # type: ignore[attr-defined]
        )

    def _push_changespec_to_history(self) -> None:
        """Push current ChangeSpec to history before navigating away.

        Called by _navigate_to_changespec() and click handlers.
        """
        from ...changespec_history import push_to_prev_stack

        entry = self._get_current_changespec_history_entry()
        if entry is not None:
            push_to_prev_stack(entry, self._changespec_history)

    def _find_changespec_by_name_and_path(
        self, name: str, file_path: str
    ) -> int | None:
        """Find a ChangeSpec by name and file_path in current filtered list.

        Args:
            name: The ChangeSpec name.
            file_path: The path to the .gp file.

        Returns:
            The index in self.changespecs, or None if not found.
        """
        for idx, cs in enumerate(self.changespecs):
            if cs.name == name and cs.file_path == file_path:
                return idx
        return None

    def _navigate_to_history_entry(self, entry: ChangeSpecHistoryEntry) -> bool:
        """Navigate to a ChangeSpec from a history entry.

        This may change the query and reload changespecs if needed.

        Args:
            entry: The history entry to navigate to.

        Returns:
            True if navigation succeeded, False otherwise.
        """
        from ....query import parse_query

        # First check if target is in current list
        target_idx = self._find_changespec_by_name_and_path(entry.name, entry.file_path)

        if target_idx is not None:
            # Target is visible - just jump to it
            self.current_idx = target_idx
            return True

        # Target not in current list - need to restore the original query
        try:
            new_parsed = parse_query(entry.query)
            self.parsed_query = new_parsed
            self.query_string = entry.query
            self._load_changespecs()  # type: ignore[attr-defined]
            self._save_current_query()  # type: ignore[attr-defined]

            # Find and select the target
            target_idx = self._find_changespec_by_name_and_path(
                entry.name, entry.file_path
            )
            if target_idx is not None:
                self.current_idx = target_idx
                return True
            else:
                # ChangeSpec no longer exists in this query result
                self.notify(  # type: ignore[attr-defined]
                    f"ChangeSpec '{entry.name}' no longer exists in query results",
                    severity="warning",
                )
                return False

        except Exception as e:
            self.notify(f"History navigation error: {e}", severity="error")  # type: ignore[attr-defined]
            return False

    def action_prev_changespec_history(self) -> None:
        """Navigate to previous ChangeSpec in history (ctrl+o)."""
        from ...changespec_history import navigate_prev

        if self.current_tab != "changespecs":
            return

        current_entry = self._get_current_changespec_history_entry()
        if current_entry is None:
            return

        prev_entry = navigate_prev(current_entry, self._changespec_history)
        if prev_entry is None:
            self.notify("No previous CL in history", severity="information")  # type: ignore[attr-defined]
            return

        self._navigate_to_history_entry(prev_entry)

    def action_next_changespec_history(self) -> None:
        """Navigate to next ChangeSpec in history (ctrl+k)."""
        from ...changespec_history import navigate_next

        if self.current_tab != "changespecs":
            return

        current_entry = self._get_current_changespec_history_entry()
        if current_entry is None:
            return

        next_entry = navigate_next(current_entry, self._changespec_history)
        if next_entry is None:
            self.notify("No next CL in history", severity="information")  # type: ignore[attr-defined]
            return

        self._navigate_to_history_entry(next_entry)

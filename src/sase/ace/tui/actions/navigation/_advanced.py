"""Advanced navigation mixin for fold mode, help modal, and history navigation."""

from __future__ import annotations

from typing import Literal

from ...changespec_history import ChangeSpecHistoryEntry
from ...models.fold_state import (
    FoldLevel,
    cycle_deltas_fold_level,
    cycle_forward,
    normalize_deltas_fold_level,
)
from .jump_hints import (
    BannerJumpTarget,
    JumpTarget,
    build_jump_hint_maps,
)
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
            self.deltas_collapsed = cycle_deltas_fold_level(self.deltas_collapsed)
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
            self.deltas_collapsed = normalize_deltas_fold_level(new_state)
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
            self.deltas_collapsed = normalize_deltas_fold_level(new_state)
        else:
            # Invalid key - cancel fold mode and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        self._refresh_current_tab()  # type: ignore[attr-defined]
        self._update_fold_tab_indicator()
        return True

    def _all_fold_states_aligned(self) -> bool:
        """Return whether all section folds are aligned under their local semantics."""
        shared_state = self.commits_collapsed
        return (
            shared_state
            == self.hooks_collapsed
            == self.mentors_collapsed
            == self.timestamps_collapsed
            and self.deltas_collapsed == normalize_deltas_fold_level(shared_state)
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

    # --- Jump To Entry ---

    def action_jump_to_entry(self) -> None:
        """Enter one-key jump mode for the current tab's left-panel entries."""
        if self.current_tab == "agents":
            self._begin_agents_jump_mode()
            return
        if self.current_tab == "changespecs":
            self._begin_changespec_jump_mode()
            return

        indices = self._jump_candidate_indices()
        if not indices:
            return
        self._entry_jump_hint_to_index, self._entry_jump_index_to_hint = (
            build_jump_hint_maps(indices)
        )
        if not self._entry_jump_hint_to_index:
            return
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_current_tab()  # type: ignore[attr-defined]

    def _begin_changespec_jump_mode(self) -> None:
        """Allocate hints across visible CLs + collapsed banners (CLs tab, grouped)."""
        targets = self._changespec_jump_targets()  # type: ignore[attr-defined]
        if not targets:
            return
        hint_to_target, _ = build_jump_hint_maps(targets)
        if not hint_to_target:
            return

        cs_hint_to_idx: dict[str, int] = {}
        cs_idx_to_hint: dict[int, str] = {}
        banner_hint_to_key: dict[str, tuple[str, ...]] = {}
        banner_key_to_hint: dict[tuple[str, ...], str] = {}
        for hint, target in hint_to_target.items():
            kind, payload = target
            if kind == "changespec":
                assert isinstance(payload, int)
                cs_hint_to_idx[hint] = payload
                cs_idx_to_hint[payload] = hint
            else:
                assert isinstance(payload, tuple)
                banner_hint_to_key[hint] = payload
                banner_key_to_hint[payload] = hint

        self._entry_jump_hint_to_index = cs_hint_to_idx
        self._entry_jump_index_to_hint = cs_idx_to_hint
        self._entry_jump_hint_to_changespec_banner = banner_hint_to_key
        self._entry_jump_changespec_banner_to_hint = banner_key_to_hint
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_current_tab()  # type: ignore[attr-defined]

    def _begin_agents_jump_mode(self) -> None:
        """Allocate hints across visible agents + collapsed banners (agents tab)."""
        targets = self._jump_candidate_targets()
        if not targets:
            return
        hint_to_target, _ = build_jump_hint_maps(targets)
        if not hint_to_target:
            return

        agent_hint_to_idx: dict[str, int] = {}
        agent_idx_to_hint: dict[int, str] = {}
        banner_hint_to_target: dict[str, BannerJumpTarget] = {}
        banner_to_hint: dict[BannerJumpTarget, str] = {}
        for hint, target in hint_to_target.items():
            if target[0] == "agent":
                agent_hint_to_idx[hint] = target[1]
                agent_idx_to_hint[target[1]] = hint
            else:
                banner_hint_to_target[hint] = target
                banner_to_hint[target] = hint

        self._entry_jump_hint_to_index = agent_hint_to_idx
        self._entry_jump_index_to_hint = agent_idx_to_hint
        self._entry_jump_hint_to_banner = banner_hint_to_target
        self._entry_jump_banner_to_hint = banner_to_hint
        self._entry_jump_mode_active = True
        self._update_jump_footer()
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _jump_candidate_indices(self) -> list[int]:
        """Return target indices for jump mode in visual order (CLs / AXE only)."""
        if self.current_tab == "changespecs":
            return list(range(len(self.changespecs)))
        if self.current_tab == "agents":
            # Kept for backward compatibility with tests / callers that
            # only need the agent indices (no banner targets).
            return [t[1] for t in self._jump_candidate_targets() if t[0] == "agent"]
        return list(range(len(self._axe_items)))  # type: ignore[attr-defined]

    def _jump_candidate_targets(self) -> list[JumpTarget]:
        """Return jump targets for the agents tab in render order.

        Walks each tag panel's grouping tree (mirroring
        :func:`_refresh_panel_widgets`) so hint characters march down the
        screen in the same order they're rendered.  Collapsed banners
        contribute ``("banner", panel_idx, group_key)`` targets;
        non-collapsed banners are non-selectable and excluded.
        """
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_panels import agents_for_panel

        registry = self._group_fold_registry
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        panel_keys = panel_group.panel_keys if panel_group is not None else [None]
        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        targets: list[JumpTarget] = []
        for panel_idx, key in enumerate(panel_keys):
            global_indices = [i for i, k in enumerate(keys_per_agent) if k == key]
            panel_agents = agents_for_panel(self._agents, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        targets.append(("banner", panel_idx, entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    targets.append(("agent", global_indices[entry.agent_idx]))
        return targets

    def _exit_entry_jump_mode(self) -> None:
        """Clear jump mode state and remove hint overlays."""
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}
        self._entry_jump_hint_to_banner = {}
        self._entry_jump_banner_to_hint = {}
        self._entry_jump_hint_to_changespec_banner = {}
        self._entry_jump_changespec_banner_to_hint = {}
        if self.current_tab == "agents":
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _save_agents_jump_anchor(self) -> None:
        """Snapshot the agents-tab cursor (agent or banner) for ``'`` back-jump."""
        panel_idx = self._panel_group.focused_idx
        if self._current_group_key is not None:
            self._entry_jump_last_agents_anchor = (
                "banner",
                panel_idx,
                self._current_group_key,
            )
        else:
            self._entry_jump_last_agents_anchor = (
                "agent",
                self.current_idx,
                panel_idx,
            )

    def _restore_agents_jump_anchor(self) -> bool:
        """Restore the saved agents-tab anchor.  Returns True on success."""
        anchor = self._entry_jump_last_agents_anchor
        if anchor is None:
            return False
        # Capture the current spot as the new anchor before jumping back so
        # a third ``'`` press toggles back to where we were.
        new_anchor: tuple[Literal["agent"], int, int] | BannerJumpTarget
        panel_idx = self._panel_group.focused_idx
        if self._current_group_key is not None:
            new_anchor = ("banner", panel_idx, self._current_group_key)
        else:
            new_anchor = ("agent", self.current_idx, panel_idx)
        self._entry_jump_last_agents_anchor = new_anchor

        if anchor[0] == "agent":
            _, agent_idx, target_panel = anchor
            if (
                target_panel != self._panel_group.focused_idx
                and 0 <= target_panel < len(self._panel_group.panel_keys)
            ):
                self._panel_group.focused_idx = target_panel
            self._current_group_key = None
            self.current_idx = agent_idx
        else:
            _, target_panel, group_key = anchor
            if (
                target_panel != self._panel_group.focused_idx
                and 0 <= target_panel < len(self._panel_group.panel_keys)
            ):
                self._panel_group.focused_idx = target_panel
            self._current_group_key = group_key
        return True

    def _handle_entry_jump_key(self, key: str) -> bool:
        """Handle one keypress while jump mode is active."""
        if not self._entry_jump_mode_active:
            return False
        if key == "escape":
            self._exit_entry_jump_mode()
            return True

        if key == "apostrophe":
            if self.current_tab == "agents":
                if self._restore_agents_jump_anchor():
                    self._exit_entry_jump_mode()
                    return True
                key = "1"
            else:
                last_idx = self._entry_jump_last_index.get(self.current_tab)
                if last_idx is not None:
                    # Save current position before jumping back
                    self._entry_jump_last_index[self.current_tab] = self.current_idx
                    self.current_idx = last_idx
                    self._exit_entry_jump_mode()
                    return True
                key = "1"

        if self.current_tab == "agents":
            banner_target = self._entry_jump_hint_to_banner.get(key)
            agent_target = self._entry_jump_hint_to_index.get(key)
            if banner_target is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            self._save_agents_jump_anchor()
            if banner_target is not None:
                _, panel_idx, group_key = banner_target
                if 0 <= panel_idx < len(self._panel_group.panel_keys):
                    if panel_idx != self._panel_group.focused_idx:
                        self._panel_group.focused_idx = panel_idx
                self._current_group_key = group_key
            else:
                assert agent_target is not None
                self._current_group_key = None
                self.current_idx = agent_target
            self._exit_entry_jump_mode()
            return True

        if self.current_tab == "changespecs":
            banner_key = self._entry_jump_hint_to_changespec_banner.get(key)
            agent_target = self._entry_jump_hint_to_index.get(key)
            if banner_key is None and agent_target is None:
                self._exit_entry_jump_mode()
                return True
            self._entry_jump_last_index[self.current_tab] = self.current_idx
            if banner_key is not None:
                self._current_changespec_group_key = banner_key  # type: ignore[attr-defined]
            else:
                assert agent_target is not None
                self._current_changespec_group_key = None  # type: ignore[attr-defined]
                self.current_idx = agent_target
            self._exit_entry_jump_mode()
            self._refresh_display()  # type: ignore[attr-defined]
            return True

        target = self._entry_jump_hint_to_index.get(key)
        if target is None:
            self._exit_entry_jump_mode()
            return True

        self._entry_jump_last_index[self.current_tab] = self.current_idx
        self.current_idx = target
        self._exit_entry_jump_mode()
        return True

    def _update_jump_footer(self) -> None:
        """Update the footer to show jump mode bindings."""
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            if self.current_tab == "agents":
                has_back = self._entry_jump_last_agents_anchor is not None
            else:
                has_back = self.current_tab in self._entry_jump_last_index
            footer.update_jump_bindings(has_back=has_back)
        except Exception:
            pass

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

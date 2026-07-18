"""Fold-mode navigation actions for the ace TUI app."""

from __future__ import annotations

from ...models.fold_state import (
    FoldLevel,
    cycle_backward,
    cycle_deltas_fold_level,
    cycle_forward,
)
from ._types import NavigationMixinBase


class FoldNavigationMixin(NavigationMixinBase):
    """Mixin providing fold mode actions."""

    # --- Fold Mode Actions ---

    def action_start_fold_mode(self) -> None:
        """Enter fold mode and wait for a tab-specific sub-key."""
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

        if self.current_tab == "agents":
            return self._handle_panel_fold_key(key, fold_keys)

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

    def _handle_panel_fold_key(
        self,
        key: str,
        fold_keys: dict[str, str | dict[str, str]],
    ) -> bool:
        """Dispatch one Agents-tab metadata-panel fold sub-key."""
        agent_keys = fold_keys.get("agents")
        if not isinstance(agent_keys, dict):
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        changed = False
        if key == agent_keys["cycle_level"]:
            self.panel_fold_level = cycle_forward(self.panel_fold_level)
            self._panel_fold_overrides.clear()
            changed = True
        elif key == agent_keys["cycle_level_back"]:
            self.panel_fold_level = cycle_backward(self.panel_fold_level)
            self._panel_fold_overrides.clear()
            changed = True
        elif key in {
            agent_keys["cycle_section"],
            agent_keys["toggle_section"],
        }:
            section_id = self._current_agent_metadata_section_id()
            if section_id is not None:
                if key == agent_keys["cycle_section"]:
                    self._panel_fold_overrides.cycle(
                        section_id,
                        self.panel_fold_level,
                    )
                else:
                    self._panel_fold_overrides.toggle(
                        section_id,
                        self.panel_fold_level,
                    )
                changed = True
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        self._refresh_current_tab()  # type: ignore[attr-defined]
        if changed:
            self._notify_regular_agent_fold_scope()
        return True

    def _current_agent_metadata_section_id(self) -> str | None:
        """Return the section occupying the metadata viewport's top row."""
        from textual.containers import VerticalScroll

        from ...widgets import AgentDetail
        from ...widgets.prompt_panel import AgentPromptPanel

        try:
            detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            panel = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
            scroll = detail.query_one("#agent-prompt-scroll", VerticalScroll)
        except Exception:
            return None

        document_row = max(0, int(scroll.scroll_y) - panel.virtual_region.y)
        return panel.resolve_section_at_row(document_row, width=panel.size.width)

    def _notify_regular_agent_fold_scope(self) -> None:
        """Explain the current rendering scope when a regular agent is selected."""
        get_selected = getattr(self, "_get_selected_agent", None)
        if not callable(get_selected):
            return
        agent = get_selected()
        if agent is None or getattr(agent, "is_clan_container", False):
            return
        self.notify(  # type: ignore[attr-defined]
            "Fold levels currently shape clan summaries"
        )

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
            footer.update_fold_bindings(current_tab=self.current_tab)
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

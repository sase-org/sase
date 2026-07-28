"""Fold-mode navigation actions for the ace TUI app."""

from __future__ import annotations

from collections.abc import Mapping

from ...models.agent_hoods import agent_owns_lane
from ...models.fold_state import (
    FoldLevel,
    cycle_deltas_fold_level,
    cycle_forward,
)
from ...models.fold_scale import (
    CLAN_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
    FoldScale,
    cycle_fold_level_forward,
    fold_level_at_position,
    resolve_summary_fold_scale,
    toggle_fold_scale_extreme,
)
from ._types import NavigationMixinBase

_FOLD_INERT_AGENT_SECTION_IDS = frozenset(
    {
        "agent-xprompt",
        "agent-prompt",
        "agent-reply",
    }
)


class FoldNavigationMixin(NavigationMixinBase):
    """Mixin providing fold mode actions."""

    # --- Fold Mode Actions ---

    def action_start_fold_mode(self) -> None:
        """Enter fold mode and wait for a tab-specific sub-key."""
        if not self._fold_mode_supported():
            return
        self._fold_mode_active = True
        self._update_fold_footer()

    def _fold_mode_supported(self) -> bool:
        """Return whether the current surface owns fold-mode content."""
        if self.current_tab == "agents":
            return self._selected_summary_fold_scale() is not None
        return self.current_tab == "changespecs" and (
            getattr(self, "current_artifacts_subtab", "prs") == "prs"
        )

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

        if not self._fold_mode_supported():
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        direct_level = self._direct_fold_level(key, fold_keys, CLAN_FOLD_SCALE)

        if direct_level is not None:
            self.commits_collapsed = direct_level
            self.hooks_collapsed = direct_level
            self.mentors_collapsed = direct_level
            self.timestamps_collapsed = direct_level
            self.deltas_collapsed = direct_level
        elif key == fold_keys["cycle_commits"]:
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

        scale = self._selected_summary_fold_scale()
        if scale is None:
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True
        changed = False
        direct_level = self._direct_fold_level(key, agent_keys, scale)
        if direct_level is not None:
            self.panel_fold_level = direct_level
            self._panel_fold_overrides.clear()
            changed = True
        elif key == agent_keys["cycle_level"]:
            self.panel_fold_level = cycle_fold_level_forward(
                self.panel_fold_level,
                scale,
            )
            self._panel_fold_overrides.clear()
            changed = True
        elif key == agent_keys["toggle_all"]:
            self.panel_fold_level = toggle_fold_scale_extreme(
                self.panel_fold_level,
                scale,
            )
            self._panel_fold_overrides.clear()
            changed = True
        elif key in {
            agent_keys["cycle_section"],
            agent_keys["toggle_section"],
        }:
            section_id = self._current_agent_metadata_section_id()
            if (
                section_id is not None
                and section_id not in _FOLD_INERT_AGENT_SECTION_IDS
            ):
                if key == agent_keys["cycle_section"]:
                    self._panel_fold_overrides.cycle(
                        section_id,
                        self.panel_fold_level,
                        scale=scale,
                    )
                else:
                    self._panel_fold_overrides.toggle(
                        section_id,
                        self.panel_fold_level,
                        scale=scale,
                    )
                changed = True
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        self._refresh_current_tab()  # type: ignore[attr-defined]
        if changed:
            self._notify_lane_fold_scope()
        return True

    @staticmethod
    def _direct_fold_level(
        key: str,
        keys: Mapping[str, str | dict[str, str]],
        scale: FoldScale,
    ) -> FoldLevel | None:
        """Resolve a configured direct-level subkey for ``scale``."""
        for position in range(1, len(TRIBE_FOLD_SCALE) + 1):
            configured = keys.get(f"set_level_{position}")
            if isinstance(configured, str) and key == configured:
                return fold_level_at_position(position, scale)
        return None

    def _selected_summary_fold_scale(self) -> FoldScale | None:
        """Return the fold scale owned by the selected Agents-tab summary."""
        whole_panel_focused = False
        for resolver_name in (
            "_resolve_focused_panel",
            "_resolve_focused_collapsed_panel",
        ):
            resolver = getattr(self, resolver_name, None)
            if callable(resolver) and resolver() is not None:
                whole_panel_focused = True
                break

        get_selected = getattr(self, "_get_selected_agent", None)
        agent = get_selected() if callable(get_selected) else None
        return resolve_summary_fold_scale(
            whole_panel_focused=whole_panel_focused,
            group_focused=getattr(self, "_current_group_key", None) is not None,
            agent=agent,
        )

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

    def _notify_lane_fold_scope(self) -> None:
        """Explain fold scope only for a lane with nothing foldable."""
        get_selected = getattr(self, "_get_selected_agent", None)
        if not callable(get_selected):
            return
        agent = get_selected()
        if agent is None or not agent_owns_lane(agent):
            return
        if getattr(agent, "is_family_container_row", False):
            return
        neighbor_count = getattr(self, "_selected_agent_neighbor_count", None)
        if callable(neighbor_count) and neighbor_count(agent) > 0:
            return
        if self._selected_lane_has_slow_tool_calls(agent):
            return
        self.notify(  # type: ignore[attr-defined]
            "Fold levels shape clan, family, neighbor, and slow-call summaries"
        )

    def _selected_lane_has_slow_tool_calls(self, agent: object) -> bool:
        """Return whether cached lane data has any qualifying slow calls."""
        count_resolver = getattr(
            self,
            "_selected_agent_slow_tool_call_count",
            None,
        )
        if callable(count_resolver):
            return count_resolver(agent) > 0

        from datetime import datetime

        from ...tools.slow import (
            normalize_slow_tool_call_threshold_ms,
            select_slow_tool_calls,
        )
        from ...widgets.prompt_panel import AgentPromptPanel
        from ...widgets.prompt_panel._agent_display_header_summary import (
            get_cached_detail_header_summary,
        )

        try:
            panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)  # type: ignore[attr-defined]
            summary = get_cached_detail_header_summary(panel, agent)  # type: ignore[arg-type]
        except Exception:
            return False
        if summary is None or not summary.slow_tool_sources:
            return False

        threshold_ms = normalize_slow_tool_call_threshold_ms(
            getattr(self, "_slow_tool_call_threshold_ms", None)
        )
        now = datetime.now()
        return any(
            select_slow_tool_calls(
                source.entries,
                now=now,
                agent_is_active=source.agent_is_active,
                agent_end_reference=source.end_reference,
                threshold_ms=threshold_ms,
            )
            for source in summary.slow_tool_sources
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
            footer.update_fold_bindings(
                current_tab=self.current_tab,
                fold_scale=(
                    self._selected_summary_fold_scale()
                    if self.current_tab == "agents"
                    else CLAN_FOLD_SCALE
                ),
            )
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

"""Compatibility facade and cross-tab routing for fold actions."""

from __future__ import annotations

from typing import Literal

from ._folding_agents import AgentTreeFoldingMixin
from ._folding_axe import AxeFoldingMixin


class AgentFoldingMixin(AgentTreeFoldingMixin, AxeFoldingMixin):
    """Route folding actions to the active TUI surface."""

    def _route_tools_detail_level(
        self, action: Literal["collapse", "expand", "min", "max"]
    ) -> bool:
        """Route fold keys to the Agents-tab Tools panel when it is active.

        Returns True when the key was handled by the Tools panel, even if the
        panel was already at the requested level.
        """
        if self.current_tab != "agents":
            return False
        try:
            from ...widgets import AgentDetail
            from ...widgets.tools_panel import ToolDetailLevel

            agent_detail = self.query_one(  # type: ignore[attr-defined]
                "#agent-detail-panel", AgentDetail
            )
        except Exception:
            return False
        if not agent_detail.is_tools_visible():
            return False

        if action == "expand":
            changed = agent_detail.expand_tools_detail()
        elif action == "collapse":
            changed = agent_detail.collapse_tools_detail()
        elif action == "max":
            changed = agent_detail.set_tools_detail_level(ToolDetailLevel.FULL)
        else:
            changed = agent_detail.set_tools_detail_level(ToolDetailLevel.COMPACT)
        if changed:
            refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh_footer):
                refresh_footer()
        return True

    def action_expand_or_layout(self) -> None:
        """Expand fold on agents/axe tab, or expand Patch group when grouped."""
        if self._route_tools_detail_level("expand"):
            return
        if self.current_tab == "agents":
            self._expand_fold()
        elif self.current_tab == "axe":
            self._expand_axe_fold()
        elif self.current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            expand = getattr(
                self,
                "_expand_patch_group_fold",
                getattr(self, "_expand_patch_group_fold", None),
            )
            if callable(expand) and expand():
                self._refresh_display()  # type: ignore[attr-defined]

    def action_hooks_or_collapse(self) -> None:
        """Navigate/collapse/jump on Agents, or collapse elsewhere."""
        if self.current_tab == "agents":
            self._collapse_fold()
        elif self.current_tab == "axe":
            self._collapse_axe_fold()
        elif self.current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            collapse = getattr(
                self,
                "_collapse_patch_group_fold",
                getattr(self, "_collapse_patch_group_fold", None),
            )
            if callable(collapse) and collapse():
                self._refresh_display()  # type: ignore[attr-defined]

    def action_hooks_or_collapse_all(self) -> None:
        """Collapse Agents context or collapse all folds on another tab."""
        if self._route_tools_detail_level("min"):
            return
        if self.current_tab == "agents":
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            if panel_focus is not None:
                if panel_focus.collapsed:
                    # Uppercase H keeps its saturated terminal behavior even
                    # though lowercase h can now leave a collapsed panel.
                    self.notify(  # type: ignore[attr-defined]
                        "Panel is already collapsed", timeout=1.5
                    )
                    return
                self._arm_panel_fold_hint_mode(intent="collapse")  # type: ignore[attr-defined]
                return

            lane_target = self._resolve_agent_lane_collapse_target()
            if lane_target is not None:
                self._collapse_agent_lane_folds(lane_target)
                return
            clan_target = self._resolve_agent_clan_collapse_target()
            if clan_target is not None:
                selected_clan_target = (
                    self._narrow_agent_clan_collapse_target_to_selection(clan_target)
                )
                if self._collapse_agent_clan_folds(selected_clan_target or clan_target):
                    return
            if not self._collapse_agent_structural_fold():
                self._collapse_group_fold()
        elif self.current_tab == "axe":
            self._collapse_all_axe_folds()
        elif self.current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            collapse = getattr(
                self,
                "_collapse_all_patch_group_folds",
                getattr(self, "_collapse_all_patch_group_folds", None),
            )
            if callable(collapse) and collapse():
                self._refresh_display()  # type: ignore[attr-defined]

    def action_expand_all_folds(self) -> None:
        """Toggle a selected-tribe fold or expand all folds on other tabs."""
        if self.current_tab == "agents":
            self.action_toggle_selected_agent_panels()  # type: ignore[attr-defined]
            return
        if self._route_tools_detail_level("max"):
            return
        if self.current_tab == "axe":
            self._expand_all_axe_folds()
        elif self.current_tab == "changespecs":  # legacy compatibility alias
            expand = getattr(
                self,
                "_expand_all_changespec_group_folds",  # legacy compatibility alias
                None,
            )
            if callable(expand) and expand():
                self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab in {
            "artifacts",
            "patches",
        }:
            expand = getattr(
                self,
                "_expand_all_patch_group_folds",
                getattr(self, "_expand_all_patch_group_folds", None),
            )
            if callable(expand) and expand():
                self._refresh_display()  # type: ignore[attr-defined]


__all__ = ["AgentFoldingMixin"]

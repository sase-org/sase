"""Compatibility facade and cross-tab routing for fold actions."""

from __future__ import annotations

from typing import Literal

from ._folding_agents import AgentTreeFoldingMixin
from ._folding_axe import AxeFoldingMixin

#: Legacy top-level tab names that always mean "the Patches pane" — no
#: subtab concept applies, so these never need the pane-key check below.
_PATCH_ONLY_TABS = frozenset(
    {
        "patches",
        "changespecs",  # legacy compatibility alias
    }
)


class AgentFoldingMixin(AgentTreeFoldingMixin, AxeFoldingMixin):
    """Route folding actions to the active TUI surface."""

    def _route_non_patch_artifacts_group_fold(
        self,
        method_name: Literal[
            "group_fold_expand",
            "group_fold_collapse",
            "group_fold_expand_all",
            "group_fold_collapse_all",
        ],
    ) -> None:
        """Route a fold action to the active non-Patches Artifacts pane.

        Every built-in Artifacts subtab besides Patches (Beads, Files,
        Plans/Documents, Stitches) owns its own grouping via
        :class:`ArtifactGroupFoldMixin` or an equivalent, exposing these
        method names.  Providers or panes without grouping simply lack the
        method, in which case this is a no-op — no bindings are added or
        renamed, this only makes the existing fold keys reach the visible
        pane instead of always mutating Patches' own state.
        """
        navigator = getattr(self, "_artifacts_entry_navigator", None)
        pane = navigator() if callable(navigator) else None
        if pane is None:
            return
        method = getattr(pane, method_name, None)
        if callable(method):
            method()

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
        elif self.current_tab in _PATCH_ONLY_TABS:
            expand = getattr(self, "_expand_patch_group_fold", None)
            if callable(expand) and expand():
                self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab == "artifacts":
            if getattr(self, "current_artifacts_pane_key", "patches") == "patches":
                expand = getattr(self, "_expand_patch_group_fold", None)
                if callable(expand) and expand():
                    self._refresh_display()  # type: ignore[attr-defined]
            else:
                self._route_non_patch_artifacts_group_fold("group_fold_expand")

    def action_hooks_or_collapse(self) -> None:
        """Navigate/collapse/jump on Agents, or collapse elsewhere."""
        if self.current_tab == "agents":
            self._collapse_fold()
        elif self.current_tab == "axe":
            self._collapse_axe_fold()
        elif self.current_tab in _PATCH_ONLY_TABS:
            collapse = getattr(self, "_collapse_patch_group_fold", None)
            if callable(collapse) and collapse():
                self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab == "artifacts":
            if getattr(self, "current_artifacts_pane_key", "patches") == "patches":
                collapse = getattr(self, "_collapse_patch_group_fold", None)
                if callable(collapse) and collapse():
                    self._refresh_display()  # type: ignore[attr-defined]
            else:
                self._route_non_patch_artifacts_group_fold("group_fold_collapse")

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

            # Resolve the selected structural target once. An open workflow
            # or family owns the next press and retreats one fold level;
            # clans stay on the established lane-before-clan ladder.
            structural_target = self._resolve_agent_structural_collapse_target()
            if structural_target is not None and structural_target.kind in {
                "workflow",
                "family",
            }:
                self._collapse_agent_structural_fold(structural_target)
                return
            lane_target = self._resolve_sase_agent_collapse_target()
            if lane_target is not None:
                self._collapse_sase_agent_folds(lane_target)
                return
            clan_target = self._resolve_agent_clan_collapse_target()
            if clan_target is not None:
                selected_clan_target = (
                    self._narrow_agent_clan_collapse_target_to_selection(clan_target)
                )
                if self._collapse_agent_clan_folds(selected_clan_target or clan_target):
                    return
            if not self._collapse_agent_structural_fold(structural_target):
                self._collapse_group_fold()
        elif self.current_tab == "axe":
            self._collapse_all_axe_folds()
        elif self.current_tab in _PATCH_ONLY_TABS:
            collapse = getattr(self, "_collapse_all_patch_group_folds", None)
            if callable(collapse) and collapse():
                self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab == "artifacts":
            if getattr(self, "current_artifacts_pane_key", "patches") == "patches":
                collapse = getattr(self, "_collapse_all_patch_group_folds", None)
                if callable(collapse) and collapse():
                    self._refresh_display()  # type: ignore[attr-defined]
            else:
                self._route_non_patch_artifacts_group_fold("group_fold_collapse_all")

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
        elif self.current_tab == "patches":
            expand = getattr(self, "_expand_all_patch_group_folds", None)
            if callable(expand) and expand():
                self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab == "artifacts":
            if getattr(self, "current_artifacts_pane_key", "patches") == "patches":
                expand = getattr(self, "_expand_all_patch_group_folds", None)
                if callable(expand) and expand():
                    self._refresh_display()  # type: ignore[attr-defined]
            else:
                self._route_non_patch_artifacts_group_fold("group_fold_expand_all")


__all__ = ["AgentFoldingMixin"]

"""Panel-group synchronization and widget key-order helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._display_panel_state import PanelRefreshStateMixin
from ._folding_panel_sweep import retire_panel_fold_sweep_records
from ._navigation_order import rendered_panel_slice
from ._panel_fold_intent import (
    effective_panel_collapses,
    panel_is_collapsed,
    retire_panel_fold_intents,
)
from ._tab_scope import sticky_key_in_scope, unstick_panel_key

if TYPE_CHECKING:
    from ...models.agent_panels import PanelKey


class PanelSyncMixin(PanelRefreshStateMixin):
    """Synchronize the panel group and order widget keys."""

    def _widget_panel_keys(
        self,
        occupancy_keys: list[PanelKey],
        *,
        occupancy_with_rows: set[PanelKey],
    ) -> list[PanelKey]:
        """Union occupancy with session-sticky keys without pre-mounting."""
        from ...models.agent_panels import normalize_panel_key

        sticky = {
            normalize_panel_key(key) for key in self._session_mounted_panel_key_set()
        }
        occupancy = [normalize_panel_key(key) for key in occupancy_keys]
        rendered_present = bool(occupancy_with_rows)
        if not rendered_present and sticky:
            merged = list(
                dict.fromkeys(key for key in (*occupancy, *sticky) if key in sticky)
            )
        else:
            merged = list(dict.fromkeys([*occupancy, *sticky]))
        return merged

    def _occupancy_keys_with_rows(self) -> set[PanelKey]:
        """Return occupancy keys that currently have at least one rendered row."""
        from ...models.agent_panels import (
            agent_is_rendered_in_agents_panel,
            normalize_panel_key,
            panel_key_per_agent,
        )

        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        return {
            normalize_panel_key(key)
            for agent, key in zip(
                self._agents,
                panel_key_per_agent(
                    self._agents, merge_tribe_panels=merge_tribe_panels
                ),
                strict=True,
            )
            if agent_is_rendered_in_agents_panel(agent)
        }

    def _sorted_widget_panel_keys(
        self,
        occupancy_keys: list[PanelKey],
        *,
        occupancy_with_rows: set[PanelKey],
    ) -> list[PanelKey]:
        """Return occupancy ∪ sticky keys in canonical expanded/collapsed order."""
        from ...models.agent_panels import AgentPanelGroup

        merged = self._widget_panel_keys(
            occupancy_keys, occupancy_with_rows=occupancy_with_rows
        )
        collapsed_keys = effective_panel_collapses(self, merged)
        expanded_intent: set[PanelKey] = getattr(self, "_expanded_panel_keys", set())
        for key in merged:
            if key not in occupancy_with_rows and key not in expanded_intent:
                collapsed_keys.add(key)
        return AgentPanelGroup.from_panel_keys(
            merged,
            getattr(self._panel_group, "focused_key", None),
            collapsed_panel_keys=collapsed_keys,
        ).panel_keys

    def _sync_panel_group(self) -> set[PanelKey]:
        """Recompute :attr:`_panel_group` from the current :attr:`_agents`.

        Returns the session-sticky keys the sync-time reconcile retired so
        the display pass can unmount their widgets in the same refresh.
        """
        from ...models.agent_panels import (
            AgentPanelGroup,
            agent_is_rendered_in_agents_panel,
            normalize_panel_key,
            panel_keys_for,
        )

        prev_focused = self._panel_group.focused_key
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        reconciled_retired = self._remember_session_mounted_occupancy()
        pending = getattr(self, "_session_sticky_pending_retired", None)
        if pending:
            reconciled_retired |= set(pending)
            pending.clear()
        if merge_tribe_panels:
            self._panel_group = AgentPanelGroup.from_agents(
                self._agents,
                prev_focused,
                merge_tribe_panels=True,
            )
        else:
            panel_keys = panel_keys_for(self._agents)
            live_keys = set(panel_keys)
            agents_with_children = getattr(self, "_agents_with_children", self._agents)
            for agent in agents_with_children:
                if agent_is_rendered_in_agents_panel(agent):
                    live_keys.add(normalize_panel_key(agent.tribe))
            live_keys.update(self._session_mounted_panel_key_set())
            retire_panel_fold_intents(self, live_keys)
            retire_panel_fold_sweep_records(self, live_keys)
            collapsed_keys = effective_panel_collapses(self, panel_keys)
            self._panel_group = AgentPanelGroup.from_panel_keys(
                panel_keys,
                prev_focused,
                collapsed_panel_keys=collapsed_keys,
            )
        known_keys = set(self._panel_group.panel_keys)
        if (
            merge_tribe_panels
            or prev_focused not in known_keys
            or not self._panel_group.panel_keys
        ):
            self._expanded_panel_focus = False
        selection_memory = getattr(self, "_panel_selection_memory", None)
        if selection_memory is not None:
            # Prune only the active scope's entries; other tabs keep theirs.
            for key in list(selection_memory):
                if not sticky_key_in_scope(self, key):
                    continue
                if unstick_panel_key(key) not in known_keys:
                    selection_memory.pop(key, None)
        # Whole-panel fold intent outlives churn within a live panel. It is
        # retired only when the panel key stops being live.

        keys_per_agent = self._panel_keys_per_agent()
        focused_key = self._panel_group.focused_key
        panel_index = self._agent_panel_index()
        # The selection is the user's intent; panel focus is derived from it
        # except when focus is deliberately parked on a non-row target.
        selection_in_range = 0 <= self.current_idx < len(self._agents)
        keys_in_range = 0 <= self.current_idx < len(keys_per_agent)
        selected_key = (
            keys_per_agent[self.current_idx]
            if selection_in_range and keys_in_range
            else None
        )
        selection_renderable = (
            selection_in_range
            and keys_in_range
            and panel_index.local_idx_for(selected_key, self.current_idx) >= 0
        )
        if selection_renderable:
            if (
                selected_key == focused_key
                and panel_index.local_idx_for(focused_key, self.current_idx) >= 0
            ):
                return reconciled_retired
            focus_reset = focused_key != prev_focused
            parked = False
            if not focus_reset:
                if getattr(self, "_expanded_panel_focus", False):
                    parked = True
                elif getattr(self, "_current_group_key", None) is not None:
                    parked = True
                elif panel_is_collapsed(self, focused_key):
                    # Whole-panel focus on a collapsed strip: collapsing is
                    # deliberate user intent, so a refresh must not drag
                    # focus out of the collapsed strip to chase the cursor.
                    parked = True
                elif panel_is_collapsed(self, selected_key):
                    # The cursor sits in a collapsed panel (e.g. fold
                    # persistence collapsed its panel before this sync).
                    # Its rows are not rendered, so focus must not follow
                    # it there; snap the cursor back out instead.
                    parked = True
                else:
                    try:
                        rendered_global, _rendered_agents = rendered_panel_slice(
                            self, focused_key
                        )
                    except Exception:
                        rendered_global = None
                    if rendered_global is not None and not rendered_global:
                        parked = True
            if selected_key in self._panel_group.panel_keys and not parked:
                self._panel_group.focused_idx = self._panel_group.panel_keys.index(
                    selected_key
                )
                self._expanded_panel_focus = False
                return reconciled_retired
        self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)
        return reconciled_retired

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[PanelKey], focused_key: PanelKey
    ) -> None:
        """Set ``current_idx`` to the first agent in the focused panel."""
        global_indices, _panel_agents = rendered_panel_slice(self, focused_key)
        if global_indices:
            self.current_idx = global_indices[0]
            return
        panel_index_fn = getattr(self, "_agent_panel_index", None)
        non_child_indices = (
            set(panel_index_fn().non_child_indices)
            if callable(panel_index_fn)
            else set(range(len(self._agents)))
        )
        for i, k in enumerate(keys_per_agent):
            if k == focused_key and i in non_child_indices:
                self.current_idx = i
                return
        self.current_idx = 0

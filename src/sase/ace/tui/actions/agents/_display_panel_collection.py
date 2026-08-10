"""Panel-group synchronization and border-title refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._display_helpers import panel_widget_id
from ._display_panel_state import PanelRefreshStateMixin
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts
from ._folding_panel_sweep import retire_panel_fold_sweep_records
from ._navigation_order import rendered_panel_slice
from ._panel_fold_intent import effective_panel_collapses, retire_panel_fold_intents

if TYPE_CHECKING:
    from rich.text import Text

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import PanelJumpTarget


class PanelCollectionMixin(PanelRefreshStateMixin):
    """Panel collection synchronization and title rendering helpers."""

    def _sync_panel_group(self) -> None:
        """Recompute :attr:`_panel_group` from the current :attr:`_agents`."""
        from ...models.agent_panels import (
            AgentPanelGroup,
            agent_is_rendered_in_agents_panel,
            normalize_panel_key,
            panel_keys_for,
        )

        prev_focused = self._panel_group.focused_key
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
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
            for stale_key in set(selection_memory) - known_keys:
                selection_memory.pop(stale_key, None)
        # Whole-panel fold intent outlives churn within a live panel. It is
        # retired only when the panel key stops being live.

        keys_per_agent = self._panel_keys_per_agent()
        focused_key = self._panel_group.focused_key
        panel_index = self._agent_panel_index()
        if 0 <= self.current_idx < len(self._agents):
            if (
                keys_per_agent[self.current_idx] != focused_key
                or panel_index.local_idx_for(focused_key, self.current_idx) < 0
            ):
                self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)
        else:
            self._snap_current_idx_to_focused_panel(keys_per_agent, focused_key)

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

    def _agent_panel_title(
        self,
        key: PanelKey,
        panel_agents: list[Agent],
        *,
        merge_tribe_panels: bool,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
        isolation_restore_marked: bool = False,
    ) -> Text:
        """Build one title with the active transient hint namespace."""
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        collapsed_keys = effective_panel_collapses(
            self, getattr(self._panel_group, "panel_keys", ())
        )
        panel_collapsed = key in collapsed_keys
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        panel_selected = bool(panel_focus is not None and panel_focus.panel_key == key)
        counts = agent_panel_counts(panel_agents, unread)
        from ...models.tribe_display import (
            tribe_display_for,
            tribe_identity_color,
        )

        tribe_display = tribe_display_for(key)
        return agent_panel_border_title(
            key,
            counts.lane_count,
            merge_tribe_panels=merge_tribe_panels,
            counts=counts,
            collapsed=panel_collapsed,
            selected=panel_selected,
            isolation_restore_marked=isolation_restore_marked,
            jump_hint=(
                panel_jump_hints.get(("panel", key)) if panel_jump_hints else None
            ),
            icon=tribe_display.icon,
            color=tribe_identity_color(key),
        )

    @staticmethod
    def _set_agent_panel_title(widget: AgentList, title: Text) -> None:
        """Set a title and let real AgentList widgets recompute their width."""
        update_title = getattr(widget, "update_border_title", None)
        if callable(update_title):
            update_title(title)
        else:
            widget.border_title = title

    def _refresh_agent_panel_titles(self) -> None:
        """Repaint only panel titles when transient numeric chips change."""
        from textual.css.query import NoMatches

        from ...widgets import AgentList

        try:
            self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return
        panel_index = self._agent_panel_index()
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        marked_keys_fn = getattr(self, "_panel_isolation_marked_keys", None)
        isolation_marked_keys = marked_keys_fn() if callable(marked_keys_fn) else set()
        for idx, key in enumerate(self._panel_group.panel_keys):
            try:
                widget = self.query_one(  # type: ignore[attr-defined]
                    f"#{panel_widget_id(idx)}", AgentList
                )
            except NoMatches:
                continue
            title = self._agent_panel_title(
                key,
                panel_index.slice_for(key).agents,
                merge_tribe_panels=merge_tribe_panels,
                isolation_restore_marked=key in isolation_marked_keys,
            )
            self._set_agent_panel_title(widget, title)
        self._focus_focused_panel_widget()

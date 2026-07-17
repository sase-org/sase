"""Panel-group synchronization and border-title refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._display_helpers import panel_widget_id
from ._display_panel_state import PanelRefreshStateMixin
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts
from ._navigation_order import rendered_panel_slice

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
        from ...models.agent_panels import AgentPanelGroup

        prev_focused = self._panel_group.focused_key
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
        collapsed_keys = getattr(self, "_collapsed_panel_keys", None)
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            prev_focused,
            merge_tag_panels=merge_tag_panels,
            collapsed_panel_keys=collapsed_keys or (),
        )
        if collapsed_keys is not None:
            before = len(collapsed_keys)
            collapsed_keys.intersection_update(self._panel_group.panel_keys)
            if len(collapsed_keys) != before:
                schedule = getattr(self, "_agents_fold_state_changed", None)
                if callable(schedule):
                    schedule()

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
        merge_tag_panels: bool,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
    ) -> Text:
        """Build one title with the active transient hint namespace."""
        unread: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        collapsed_keys: set[PanelKey] = getattr(self, "_collapsed_panel_keys", set())
        panel_collapsed = key in collapsed_keys
        selection_hint = None
        if getattr(self, "_panel_fold_hint_mode_active", False):
            selection_hint = getattr(self, "_panel_fold_key_to_hint", {}).get(key)
        counts = agent_panel_counts(panel_agents, unread)
        return agent_panel_border_title(
            key,
            counts.total,
            merge_tag_panels=merge_tag_panels,
            counts=counts,
            collapsed=panel_collapsed,
            jump_hint=(
                panel_jump_hints.get(("panel", key))
                if panel_collapsed and panel_jump_hints
                else None
            ),
            selection_hint=selection_hint,
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
        merge_tag_panels = getattr(self, "_agent_panels_grouped", False)
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
                merge_tag_panels=merge_tag_panels,
            )
            self._set_agent_panel_title(widget, title)
        self._focus_focused_panel_widget()

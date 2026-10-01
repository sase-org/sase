"""Panel border-title rendering and refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._display_helpers import panel_widget_id_for_key
from ._display_panel_state import PanelRefreshStateMixin
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts
from ._panel_fold_intent import effective_panel_collapses

if TYPE_CHECKING:
    from rich.text import Text

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import PanelJumpTarget


class PanelTitlesMixin(PanelRefreshStateMixin):
    """Build and repaint agent panel border titles."""

    def _agent_panel_title_for_key(
        self,
        key: PanelKey,
        panel_agents: list[Agent],
    ) -> Text:
        """Build one title with the active hints and restore markers."""
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        marked_keys_fn = getattr(self, "_panel_isolation_marked_keys", None)
        isolation_marked_keys = marked_keys_fn() if callable(marked_keys_fn) else set()
        restore_marked_fn = getattr(self, "_panel_fold_restore_marked_keys", None)
        fold_restore_marked = restore_marked_fn() if callable(restore_marked_fn) else {}
        title_hints = getattr(self, "_active_panel_title_jump_hints", None)
        panel_jump_hints = title_hints() if callable(title_hints) else None
        return self._agent_panel_title(
            key,
            panel_agents,
            merge_tribe_panels=merge_tribe_panels,
            panel_jump_hints=panel_jump_hints,
            isolation_restore_marked=key in isolation_marked_keys,
            fold_restore_marked_count=len(fold_restore_marked.get(key, ())),
        )

    def _agent_panel_title(
        self,
        key: PanelKey,
        panel_agents: list[Agent],
        *,
        merge_tribe_panels: bool,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
        isolation_restore_marked: bool = False,
        fold_restore_marked_count: int = 0,
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
        from ...widgets.decks.layout import SidebarMode

        from ._panel_layout import merged_panel_title_for_owner

        merged_title = (
            merged_panel_title_for_owner(self) if merge_tribe_panels else None
        )
        if getattr(self, "_agents_sidebar_mode", None) is SidebarMode.RAIL:
            from ...widgets._agent_list_render_rail import rail_panel_title

            return rail_panel_title(
                key=key,
                hint=(
                    panel_jump_hints.get(("panel", key)) if panel_jump_hints else None
                ),
                selected=panel_selected,
                collapsed=panel_collapsed,
                merged=merge_tribe_panels,
                merged_title=merged_title,
                icon=tribe_display.icon,
                color=tribe_identity_color(key),
                counts=counts,
            )
        return agent_panel_border_title(
            key,
            counts.lane_count,
            merge_tribe_panels=merge_tribe_panels,
            merged_title=merged_title,
            counts=counts,
            collapsed=panel_collapsed,
            selected=panel_selected,
            isolation_restore_marked=isolation_restore_marked,
            fold_restore_marked_count=fold_restore_marked_count,
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
        for key in self._panel_group.panel_keys:
            try:
                widget = self.query_one(  # type: ignore[attr-defined]
                    f"#{panel_widget_id_for_key(key)}", AgentList
                )
            except NoMatches:
                continue
            title = self._agent_panel_title_for_key(
                key,
                panel_index.slice_for(key).agents,
            )
            self._set_agent_panel_title(widget, title)
        self._focus_focused_panel_widget()

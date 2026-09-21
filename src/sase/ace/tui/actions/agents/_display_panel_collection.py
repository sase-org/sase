"""Panel-group synchronization and border-title refresh helpers."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from ._display_helpers import panel_widget_id_for_key
from ._display_panel_state import PanelRefreshStateMixin
from ._display_panel_titles import agent_panel_border_title, agent_panel_counts
from ._folding_panel_sweep import retire_panel_fold_sweep_records
from ._navigation_order import rendered_panel_slice
from ._panel_fold_intent import (
    effective_panel_collapses,
    panel_is_collapsed,
    retire_panel_fold_intents,
)

if TYPE_CHECKING:
    from rich.text import Text

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import PanelJumpTarget


class PanelCollectionMixin(PanelRefreshStateMixin):
    """Panel collection synchronization and title rendering helpers."""

    def _session_sticky_query_value(self) -> str:
        """Return the committed Agents query that owns session-sticky panels."""
        return getattr(self, "_agent_search_query", "") or ""

    def _session_mounted_identity_map(
        self,
    ) -> dict[PanelKey, set[tuple[AgentType, str, str | None]]]:
        """Return the identities that mounted each key, cleared on query change."""
        query = self._session_sticky_query_value()
        last = getattr(self, "_session_sticky_query", None)
        mounted = getattr(self, "_session_mounted_panel_identities", None)
        if mounted is None:
            mounted = {}
            self._session_mounted_panel_identities = mounted  # type: ignore[attr-defined]
        if last is None:
            self._session_sticky_query = query  # type: ignore[attr-defined]
        elif last != query:
            mounted.clear()
            self._session_sticky_query = query  # type: ignore[attr-defined]
        return mounted

    def _session_mounted_panel_key_set(self) -> set[PanelKey]:
        """Return a snapshot of mounted-this-session keys."""
        return set(self._session_mounted_identity_map())

    def _remember_session_mounted_occupancy(self) -> None:
        """Record the identities behind each key that has rendered occupancy."""
        from ...models.agent_panels import (
            agent_is_rendered_in_agents_panel,
            normalize_panel_key,
            panel_key_per_agent,
        )

        mounted = self._session_mounted_identity_map()
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        keys = panel_key_per_agent(self._agents, merge_tribe_panels=merge_tribe_panels)
        for agent, key in zip(self._agents, keys, strict=True):
            if agent_is_rendered_in_agents_panel(agent):
                mounted.setdefault(normalize_panel_key(key), set()).add(agent.identity)

    def _retire_session_mounted_identities(
        self, identities: Collection[tuple[AgentType, str, str | None]]
    ) -> set[PanelKey]:
        """Drop explicitly removed identities and retire keys left with none.

        Only user-driven removals (dismiss, kill, proc-shell dismiss) call this.
        A tribe's agents merely being absent from the roster never retires its
        key: an incomplete or bounded load is not proof that a row is gone.
        Returns the keys that were retired.
        """
        mounted = self._session_mounted_identity_map()
        retired: set[PanelKey] = set()
        for key in list(mounted):
            remaining = mounted[key]
            if remaining.isdisjoint(identities):
                continue
            remaining.difference_update(identities)
            if not remaining:
                del mounted[key]
                retired.add(key)
        return retired

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
        self._remember_session_mounted_occupancy()
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
            for stale_key in set(selection_memory) - known_keys:
                selection_memory.pop(stale_key, None)
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
                return
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
                return
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
        return agent_panel_border_title(
            key,
            counts.lane_count,
            merge_tribe_panels=merge_tribe_panels,
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
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        marked_keys_fn = getattr(self, "_panel_isolation_marked_keys", None)
        isolation_marked_keys = marked_keys_fn() if callable(marked_keys_fn) else set()
        restore_marked_fn = getattr(self, "_panel_fold_restore_marked_keys", None)
        fold_restore_marked = restore_marked_fn() if callable(restore_marked_fn) else {}
        title_hints = getattr(self, "_active_panel_title_jump_hints", None)
        panel_jump_hints = title_hints() if callable(title_hints) else None
        for key in self._panel_group.panel_keys:
            try:
                widget = self.query_one(  # type: ignore[attr-defined]
                    f"#{panel_widget_id_for_key(key)}", AgentList
                )
            except NoMatches:
                continue
            title = self._agent_panel_title(
                key,
                panel_index.slice_for(key).agents,
                merge_tribe_panels=merge_tribe_panels,
                panel_jump_hints=panel_jump_hints,
                isolation_restore_marked=key in isolation_marked_keys,
                fold_restore_marked_count=len(fold_restore_marked.get(key, ())),
            )
            self._set_agent_panel_title(widget, title)
        self._focus_focused_panel_widget()

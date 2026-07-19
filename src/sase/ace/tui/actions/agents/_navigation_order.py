"""Rendered-order helpers for Agents-tab navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._fold_scope import focused_panel_fold_registry, panel_fold_registry

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey


def rendered_panel_slice(owner: Any, key: Any) -> tuple[list[int], list[Agent]]:
    """Return rendered global indices and agents for a panel."""
    index_fn = getattr(owner, "_agent_panel_index", None)
    if callable(index_fn):
        slot = index_fn().slice_for(key)
        return slot.global_indices, slot.agents

    from ...models.agent_panels import (
        agent_is_rendered_in_agents_panel,
        agents_for_panel,
        panel_key_per_agent,
    )

    agents = owner._agents
    keys = panel_key_per_agent(
        agents,
        merge_tribe_panels=getattr(owner, "_agent_panels_grouped", False),
    )
    global_indices = [
        i
        for i, panel_key in enumerate(keys)
        if panel_key == key and agent_is_rendered_in_agents_panel(agents[i])
    ]
    return global_indices, agents_for_panel(
        agents,
        key,
        merge_tribe_panels=getattr(owner, "_agent_panels_grouped", False),
    )


class AgentNavigationOrderMixin:
    """Mixin providing rendered agent row ordering and focus restoration."""

    _agents: list[Agent]
    current_idx: int
    _current_group_key: tuple[str, ...] | None
    _nav_stops_cache: tuple[Any, ...] | None

    def _agents_visible_order(self) -> list[int]:
        """Return global agent indices in the order rendered on the focused panel.

        Mirrors :func:`AgentList.update_list`'s tree walk so j/k
        navigation steps through the same sequence the user sees.
        Agents inside collapsed groups are excluded - their indices
        never appear because the renderer hides them. Only agents in
        the currently focused tribe panel are returned; workflow children
        inherit parent grouping (per ``_grouping_keys_for``) and so
        render contiguous with their parent.
        """
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_panels import agent_is_rendered_in_agents_panel

        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            registry = panel_fold_registry(self, None)
            global_indices = [
                i
                for i, agent in enumerate(self._agents)
                if agent_is_rendered_in_agents_panel(agent)
            ]
            panel_agents = [self._agents[i] for i in global_indices]
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            return [
                global_indices[entry.agent_idx]
                for entry in tree
                if entry.kind == "agent" and entry.agent_idx is not None
            ]
        focused_key = panel_group.focused_key
        if focused_key in getattr(self, "_collapsed_panel_keys", set()):
            return []
        registry = panel_fold_registry(self, focused_key)
        global_indices, panel_agents = rendered_panel_slice(self, focused_key)
        tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
        return [
            global_indices[entry.agent_idx]
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    @staticmethod
    def _navigation_stop_maps(
        stops: list[tuple[str, int | tuple[str, ...]]],
    ) -> tuple[dict[int, int], dict[tuple[str, ...], int]]:
        agent_positions: dict[int, int] = {}
        banner_positions: dict[tuple[str, ...], int] = {}
        for pos, (kind, payload) in enumerate(stops):
            if kind == "agent":
                assert isinstance(payload, int)
                agent_positions[payload] = pos
            else:
                assert isinstance(payload, tuple)
                banner_positions[payload] = pos
        return agent_positions, banner_positions

    def _panel_navigation_stops(
        self,
        *,
        include_panel_focus: bool = False,
    ) -> list[tuple[str, int | tuple[str, ...]]]:
        """Return the focused panel's selectable rows in render order.

        Each entry is ``("agent", global_idx)`` for a visible agent row
        or ``("banner", group_key)`` for a collapsed banner row. Used
        by j/k navigation to cycle through every selectable stop -
        including stepping in and out of collapsed groups.

        Memoized: under j/k autorepeat the inputs (agents list,
        focused panel, fold state, grouping mode) don't change between
        keystrokes, so the tree rebuild is amortized to one per refresh
        cycle. Cache invalidates implicitly when any input changes
        identity / version.
        """
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_panels import agent_is_rendered_in_agents_panel

        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        panel_group = getattr(self, "_panel_group", None)
        registry = focused_panel_fold_registry(self)
        focused_key = panel_group.focused_key if panel_group is not None else None
        focused_panel_collapsed = panel_group is not None and focused_key in getattr(
            self, "_collapsed_panel_keys", set()
        )
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        whole_panel_focused = focused_panel_collapsed or (
            callable(resolve_panel) and resolve_panel() is not None
        )
        suppress_panel_rows = whole_panel_focused and not include_panel_focus

        fold_version = registry.version if registry is not None else 0
        cached = getattr(self, "_nav_stops_cache", None)
        if (
            cached is not None
            and cached[0] is self._agents
            and cached[1] is panel_group
            and cached[2]
            == (panel_group.focused_idx if panel_group is not None else None)
            and cached[3] == fold_version
            and cached[4] is mode
            and cached[5] == merge_tribe_panels
            and cached[6] == focused_panel_collapsed
            and cached[7] == suppress_panel_rows
            and cached[8] == include_panel_focus
        ):
            return cached[9]

        if suppress_panel_rows:
            stops: list[tuple[str, int | tuple[str, ...]]] = []
        elif panel_group is None:
            global_indices = [
                i
                for i, agent in enumerate(self._agents)
                if agent_is_rendered_in_agents_panel(agent)
            ]
            panel_agents = [self._agents[i] for i in global_indices]
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            stops = []
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        stops.append(("banner", entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    stops.append(("agent", global_indices[entry.agent_idx]))
        else:
            global_indices, panel_agents = rendered_panel_slice(self, focused_key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            stops = []
            for entry in tree:
                if entry.kind == "group" and entry.group is not None:
                    if entry.group.is_collapsed:
                        stops.append(("banner", entry.group.group_key))
                elif entry.kind == "agent" and entry.agent_idx is not None:
                    stops.append(("agent", global_indices[entry.agent_idx]))

        agent_positions, banner_positions = (
            AgentNavigationOrderMixin._navigation_stop_maps(stops)
        )
        self._nav_stops_cache = (
            self._agents,
            panel_group,
            panel_group.focused_idx if panel_group is not None else None,
            fold_version,
            mode,
            merge_tribe_panels,
            focused_panel_collapsed,
            suppress_panel_rows,
            include_panel_focus,
            stops,
            agent_positions,
            banner_positions,
        )
        return stops

    def _panel_navigation_stop_maps(
        self,
    ) -> tuple[dict[int, int], dict[tuple[str, ...], int]]:
        """Return reverse maps for the focused panel's selectable stops."""
        stops = self._panel_navigation_stops()
        cached = getattr(self, "_nav_stops_cache", None)
        if cached is not None and len(cached) >= 12 and cached[9] is stops:
            return cached[10], cached[11]
        return AgentNavigationOrderMixin._navigation_stop_maps(stops)

    def _capture_focused_visible_pos(self) -> int | None:
        """Return the rendered selectable-row position of the current focus.

        The Agents tab can focus either an agent row (``current_idx``)
        or a collapsed group banner (``_current_group_key``). Capture the
        position in ``_panel_navigation_stops()`` so removals restore to
        the next surviving selectable row in the same order j/k uses.
        Returns ``None`` when the current focus is no longer rendered.
        """
        agents = getattr(self, "_agents", None)
        if not agents:
            return None

        stops: list[tuple[str, int | tuple[str, ...]]] = []
        try:
            stops = self._panel_navigation_stops()
        except Exception:
            pass

        stop_maps = getattr(self, "_panel_navigation_stop_maps", None)
        if callable(stop_maps):
            try:
                agent_positions, banner_positions = stop_maps()
            except Exception:
                agent_positions, banner_positions = {}, {}
        elif stops:
            agent_positions, banner_positions = (
                AgentNavigationOrderMixin._navigation_stop_maps(stops)
            )
        else:
            agent_positions, banner_positions = {}, {}

        current_group_key = getattr(self, "_current_group_key", None)
        if current_group_key is not None:
            pos = banner_positions.get(current_group_key)
            if pos is not None:
                return pos

        if 0 <= self.current_idx < len(agents):
            pos = agent_positions.get(self.current_idx)
            if pos is not None:
                return pos
        return None

    def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
        """Re-anchor focus after an in-memory removal.

        ``prior_visible_pos`` is the pre-removal position in
        ``_panel_navigation_stops()``. After removal, the same position
        points at the row visually below the removed one, clamped to the
        last surviving stop. Agent stops clear banner focus and update
        ``current_idx``; banner stops preserve banner focus and keep
        ``current_idx`` clamped to a valid backing index.
        """
        if not self._agents:
            self.current_idx = 0
            self._current_group_key = None
            return

        if self.current_idx >= len(self._agents):
            self.current_idx = len(self._agents) - 1
        if self.current_idx < 0:
            self.current_idx = 0

        try:
            stops = self._panel_navigation_stops()
        except Exception:
            stops = []

        if prior_visible_pos is not None and stops:
            kind, payload = stops[min(prior_visible_pos, len(stops) - 1)]
            if kind == "banner":
                assert isinstance(payload, tuple)
                self._current_group_key = payload
            else:
                assert isinstance(payload, int)
                self._current_group_key = None
                self.current_idx = payload
            return

        if self._current_group_key is not None and not any(
            kind == "banner" and payload == self._current_group_key
            for kind, payload in stops
        ):
            self._current_group_key = None

    def _panel_idx_for_agent(self, agent_idx: int) -> int | None:
        """Return the current rendered panel index for a global agent index."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None or not (0 <= agent_idx < len(self._agents)):
            return None

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        if not (0 <= agent_idx < len(keys_per_agent)):
            return None

        panel_key = keys_per_agent[agent_idx]
        try:
            return panel_group.panel_keys.index(panel_key)
        except ValueError:
            return None

    def _visible_agent_panel_indices(
        self,
        *,
        include_collapsed_panels: bool = False,
    ) -> dict[int, int | None]:
        """Return visible global agent indices mapped to their panel index.

        The no-panel fallback intentionally keeps the old focused-list
        behavior used by tests and single-list contexts.  Callers may opt in
        to rows that would render if a whole collapsed panel were expanded;
        in-panel folds and all other rendering filters remain authoritative.
        """
        from ...models.agent_groups import GroupingMode, build_agent_tree

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return {
                idx: None
                for idx in self._agents_visible_order()
                if 0 <= idx < len(self._agents)
            }

        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        visible: dict[int, int | None] = {}
        collapsed_keys: set[PanelKey] = getattr(self, "_collapsed_panel_keys", set())

        for key in panel_group.panel_keys:
            if key in collapsed_keys and not include_collapsed_panels:
                continue
            registry = panel_fold_registry(self, key)
            global_indices, panel_agents = rendered_panel_slice(self, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind != "agent" or entry.agent_idx is None:
                    continue
                if not (0 <= entry.agent_idx < len(global_indices)):
                    continue
                global_idx = global_indices[entry.agent_idx]
                panel_idx = self._panel_idx_for_agent(global_idx)
                if panel_idx is not None:
                    visible[global_idx] = panel_idx
        return visible

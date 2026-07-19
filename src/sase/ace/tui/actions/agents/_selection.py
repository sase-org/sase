"""Shared selected-agent helpers for Agents-tab actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._panel_fold_intent import panel_is_collapsed

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey
    from ...models.agent_tribe_summary import (
        AgentPanelFocus,
        AgentTribeSummarySnapshot,
        CollapsedAgentPanelFocus,
    )

type PanelSelectionStop = tuple[
    Literal["agent", "banner"],
    int | tuple[str, ...],
]


class AgentSelectionMixin:
    """Mixin providing selected-agent and focused-panel accessors."""

    _agents: list[Agent]
    current_idx: int
    current_attempt_number: int | None
    _current_group_key: tuple[str, ...] | None
    _expanded_panel_focus: bool
    _panel_selection_memory: dict[
        PanelKey,
        tuple[str, int | tuple[str, ...]],
    ]

    def _resolve_focused_panel(self) -> AgentPanelFocus | None:
        """Resolve collapsed or explicitly selected expanded-panel focus."""
        if getattr(self, "current_tab", None) != "agents":
            return None
        if getattr(self, "_agent_panels_grouped", False):
            return None
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return None
        panel_keys = getattr(panel_group, "panel_keys", None)
        focused_idx = getattr(panel_group, "focused_idx", -1)
        if panel_keys is None or not (0 <= focused_idx < len(panel_keys)):
            return None
        panel_key = panel_keys[focused_idx]
        collapsed = panel_is_collapsed(self, panel_key)
        if not collapsed and not getattr(self, "_expanded_panel_focus", False):
            return None

        from ...models.agent_tribe_summary import AgentPanelFocus

        return AgentPanelFocus(panel_key=panel_key, collapsed=collapsed)

    def _resolve_focused_collapsed_panel(
        self,
    ) -> CollapsedAgentPanelFocus | None:
        """Resolve whole-panel focus, with ``None`` panel keys kept explicit."""
        focus = self._resolve_focused_panel()
        if focus is None or not focus.collapsed:
            return None

        from ...models.agent_tribe_summary import CollapsedAgentPanelFocus

        return CollapsedAgentPanelFocus(panel_key=focus.panel_key)

    def _remember_focused_panel_selection(
        self,
        stop: PanelSelectionStop | None = None,
    ) -> None:
        """Remember the current selectable row for the focused panel."""
        if getattr(self, "current_tab", None) != "agents":
            return
        if self._resolve_focused_panel() is not None:
            return
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None or getattr(self, "_agent_panels_grouped", False):
            return

        panel_key = panel_group.focused_key
        if stop is None:
            group_key = getattr(self, "_current_group_key", None)
            if group_key is not None:
                stop = ("banner", tuple(group_key))
            elif 0 <= self.current_idx < len(getattr(self, "_agents", ())):
                stop = ("agent", self.current_idx)
            else:
                return

        if stop is None:  # Defensive narrowing for static type checkers.
            return
        kind, payload = stop
        if kind == "agent":
            if not isinstance(payload, int):
                return
            panel_index = getattr(self, "_agent_panel_index", None)
            if callable(panel_index):
                if payload not in panel_index().slice_for(panel_key).global_indices:
                    return
        elif not isinstance(payload, tuple):
            return

        memory = getattr(self, "_panel_selection_memory", None)
        if memory is None:
            memory = {}
            self._panel_selection_memory = memory
        memory[panel_key] = stop

    def _activate_focused_panel(self) -> bool:
        """Select the focused expanded panel while retaining its row anchor."""
        panel_group = getattr(self, "_panel_group", None)
        if (
            getattr(self, "current_tab", None) != "agents"
            or panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or len(panel_group.panel_keys) <= 1
        ):
            return False
        if self._resolve_focused_panel() is not None:
            return True

        self._remember_focused_panel_selection()
        self._expanded_panel_focus = True
        self._current_group_key = None  # type: ignore[attr-defined]
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]
        self._refresh_panel_focus_state(old_focused_idx=None)
        return True

    def _exit_expanded_panel_focus(self) -> bool:
        """Descend into a selected expanded panel at its remembered stop."""
        focus = self._resolve_focused_panel()
        if focus is None or focus.collapsed:
            return False

        stops_fn = getattr(self, "_panel_navigation_stops", None)
        stops: list[PanelSelectionStop] = []
        if callable(stops_fn):
            try:
                stops = stops_fn(include_panel_focus=True)
            except TypeError:
                stops = stops_fn()
        remembered = getattr(self, "_panel_selection_memory", {}).get(focus.panel_key)
        destination = (
            remembered if remembered in stops else (stops[0] if stops else None)
        )

        self._expanded_panel_focus = False
        if destination is not None:
            focus_stop = getattr(self, "_focus_panel_navigation_stop", None)
            if callable(focus_stop):
                focus_stop(destination)
        self._refresh_panel_focus_state(old_focused_idx=None)
        return True

    def _refresh_panel_focus_state(
        self,
        *,
        old_focused_idx: int | None,
        render_detail_immediate: bool = True,
    ) -> None:
        """Selectively repaint panel chrome, cursor state, and detail."""
        refresh_panel = getattr(self, "_refresh_focused_agent_panel", None)
        if callable(refresh_panel):
            refresh_panel(old_focused_idx=old_focused_idx)
        else:
            refresh_display = getattr(self, "_refresh_agents_display", None)
            if callable(refresh_display):
                refresh_display(list_changed=False)
        refresh_detail = getattr(self, "_refresh_agent_focus_detail", None)
        if callable(refresh_detail):
            if render_detail_immediate:
                refresh_detail()
            else:
                refresh_detail(render_immediate=False)

    def _focused_tribe_summary(
        self,
    ) -> AgentTribeSummarySnapshot | None:
        """Build the current whole-panel tribe snapshot from cached rows."""
        focus = self._resolve_focused_panel()
        if focus is None:
            return None
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        agents = panel_index.slice_for(focus.panel_key).agents

        from ...models.agent_tribe_summary import (
            build_agent_tribe_summary_snapshot,
        )

        return build_agent_tribe_summary_snapshot(
            focus.panel_key,
            agents,
            panel_collapsed=(focus.collapsed),
            unread_ids=getattr(self, "_unread_completed_agent_ids", set()),
            marked_ids=getattr(self, "_marked_agents", set()),
        )

    def _get_selected_agent(self) -> Agent | None:
        """Get the currently selected agent, or None if no valid selection."""
        if self._resolve_focused_panel() is not None:
            return None
        if self._agents and 0 <= self.current_idx < len(self._agents):
            from ...models.agent_panels import agent_is_rendered_in_agents_panel

            agent = self._agents[self.current_idx]
            if agent_is_rendered_in_agents_panel(agent):
                return agent
        return None

    def _agents_in_focused_panel(self) -> list[Agent]:
        """Return the agents in the currently focused tribe panel.

        Falls back to the full agent list when ``_panel_group`` has not
        been built yet (early lifecycle window before the first refresh).
        """
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            from ...models.agent_panels import agent_is_rendered_in_agents_panel

            return [a for a in self._agents if agent_is_rendered_in_agents_panel(a)]
        from ._navigation_order import rendered_panel_slice

        _global_indices, agents = rendered_panel_slice(self, panel_group.focused_key)
        return list(agents)

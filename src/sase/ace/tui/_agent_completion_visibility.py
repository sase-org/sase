"""Visible Agents-tab row collection for completion candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent


def visible_agent_completion_agents(app: object) -> list[Agent]:
    """Return agents currently visible across all Agents-tab panels."""
    from textual.css.query import NoMatches

    from sase.ace.tui.actions.agents._display_helpers import panel_widget_id
    from sase.ace.tui.models.agent_panels import agent_is_rendered_in_agents_panel
    from sase.ace.tui.widgets import AgentList

    panel_group = getattr(app, "_panel_group", None)
    panel_keys = getattr(panel_group, "panel_keys", [])
    panel_count = len(panel_keys)
    query_one = getattr(app, "query_one", None)
    if callable(query_one):
        visible: list[Agent] = []
        seen_identities: set[object] = set()
        queried_widget = False
        for panel_idx in range(panel_count):
            try:
                widget = query_one(f"#{panel_widget_id(panel_idx)}", AgentList)
            except NoMatches:
                continue
            queried_widget = True
            for agent in widget.visible_agents():
                if agent.identity in seen_identities:
                    continue
                seen_identities.add(agent.identity)
                visible.append(agent)
        if queried_widget:
            return visible

    agents = list(getattr(app, "_agents", []))
    order_fn = getattr(app, "_agents_visible_order", None)
    if callable(order_fn):
        try:
            return [agents[idx] for idx in order_fn() if 0 <= idx < len(agents)]
        except Exception:
            pass

    return [
        candidate
        for candidate in agents
        if agent_is_rendered_in_agents_panel(candidate)
    ]


__all__ = ["visible_agent_completion_agents"]

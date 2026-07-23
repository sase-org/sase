"""Visible Agents-tab row collection for completion candidates."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent


def _dedupe_agent_identities(agents: Iterable[Agent]) -> list[Agent]:
    """Return the first row for each stable agent identity."""
    deduplicated: list[Agent] = []
    seen_identities: set[object] = set()
    for agent in agents:
        if agent.identity in seen_identities:
            continue
        seen_identities.add(agent.identity)
        deduplicated.append(agent)
    return deduplicated


def _rendered_agent_completion_agents(app: object) -> list[Agent]:
    """Return physically rendered rows from the best available UI snapshot."""
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
        queried_widget = False
        for panel_idx in range(panel_count):
            try:
                widget = query_one(f"#{panel_widget_id(panel_idx)}", AgentList)
            except NoMatches:
                continue
            queried_widget = True
            visible.extend(widget.visible_agents())
        if queried_widget:
            return _dedupe_agent_identities(visible)

    agents = list(getattr(app, "_agents", []))
    order_fn = getattr(app, "_agents_visible_order", None)
    if callable(order_fn):
        try:
            ordered = [agents[idx] for idx in order_fn() if 0 <= idx < len(agents)]
        except Exception:
            pass
        else:
            return _dedupe_agent_identities(ordered)

    return _dedupe_agent_identities(
        candidate
        for candidate in agents
        if agent_is_rendered_in_agents_panel(candidate)
    )


def visible_agent_completion_agents(app: object) -> list[Agent]:
    """Return completion-eligible rows across all Agents-tab panels.

    The base snapshot contains physically rendered rows. Rows hidden only by a
    collapsed outer clan are added from the read-only prospective projection;
    search, grouping, dismissal, STARTING exclusion, and inner folds remain in
    effect.
    """
    rendered = _rendered_agent_completion_agents(app)
    if getattr(app, "_fold_manager", None) is None:
        return rendered

    complete = list(
        getattr(app, "_agents_with_children", None) or getattr(app, "_agents", ()) or ()
    )
    if not complete:
        return rendered

    from sase.ace.tui.actions.agents._prospective_clan import (
        prospective_clan_projection,
    )

    projection = prospective_clan_projection(app, complete)
    if not projection.members:
        return rendered

    rows_by_identity = {agent.identity: agent for agent in rendered}
    for identity, target in projection.members.items():
        rows_by_identity.setdefault(identity, target.agent)

    fallback_offset = max(projection.display_order_by_identity.values(), default=-1) + 1
    base_order_by_identity = {
        agent.identity: index for index, agent in enumerate(rendered)
    }
    return sorted(
        rows_by_identity.values(),
        key=lambda agent: projection.display_order_by_identity.get(
            agent.identity,
            fallback_offset + base_order_by_identity.get(agent.identity, 0),
        ),
    )


__all__ = ["visible_agent_completion_agents"]

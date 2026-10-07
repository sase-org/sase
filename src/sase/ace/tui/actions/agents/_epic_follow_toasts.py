"""Coalesced toasts for live `%wait(for_epic=)` follow transitions.

When an agent reload applies, each waiter's previous and new FOLLOWING sets
are compared off the render path and one toast per newly followed epic is
emitted, coalesced across waiters. Startup loads never toast. Pure
in-memory set arithmetic over already-loaded agents: never touches the
filesystem.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _waiter_follow_edges(agent: Any) -> frozenset[tuple[str, str]]:
    """Return the `(epic_id, launcher)` FOLLOWING edges of one waiter."""
    from sase.ace.tui.models.agent_time import wait_display_agent
    from sase.core.wait_epic_follow_view import epic_follow_views

    wait_agent = wait_display_agent(agent)
    allowed = set(wait_agent.waiting_for)
    edges: set[tuple[str, str]] = set()
    for view in epic_follow_views(wait_agent):
        if view.state != "following" or view.target not in allowed:
            continue
        for epic_id in view.epic_ids:
            edges.add((epic_id, view.target))
    return frozenset(edges)


def _waiter_name(agent: Any) -> str:
    """Return the display name of one waiter for toast text."""
    for attr in ("presented_agent_name", "agent_name", "display_name"):
        name = getattr(agent, attr, None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "an agent"


def epic_follow_toast_messages(
    previous: Mapping[Any, frozenset[tuple[str, str]]],
    current: Mapping[Any, frozenset[tuple[str, str]]],
    names: Mapping[Any, str],
) -> list[str]:
    """Return one coalesced toast per newly followed epic.

    *previous* and *current* map waiter identities to their FOLLOWING
    `(epic_id, launcher)` edges; *names* maps the same identities to
    display names. Only edges present in *current* but absent from
    *previous* toast, grouped by epic and launcher so three waiters on one
    epic emit a single toast. Output order is deterministic.
    """
    new_by_epic: dict[tuple[str, str], set[Any]] = {}
    for identity, edges in current.items():
        before = previous.get(identity, frozenset())
        for edge in edges:
            if edge in before:
                continue
            new_by_epic.setdefault(edge, set()).add(identity)
    messages: list[str] = []
    for epic_id, launcher in sorted(new_by_epic):
        waiters = sorted(
            new_by_epic[(epic_id, launcher)],
            key=lambda identity: (names.get(identity, ""), str(identity)),
        )
        if len(waiters) == 1:
            messages.append(
                f"{names.get(waiters[0], 'an agent')} now waits on epic "
                f"{epic_id} (launched by {launcher})"
            )
        else:
            messages.append(
                f"{len(waiters)} agents now wait on epic {epic_id} "
                f"(launched by {launcher})"
            )
    return messages


def announce_epic_follow_transitions(
    notify: object,
    previous_agents: Iterable[Any],
    current_agents: Iterable[Any],
    *,
    first_load: bool,
) -> list[str]:
    """Compare FOLLOWING sets across a reload and toast each new follow.

    Returns the emitted messages. Never toasts on the first (startup) load;
    it only records the baseline. *notify* is the app's toast callable and
    is never called when there is nothing new. Exceptions from *notify*
    propagate to the caller, which must guard them.
    """
    current_list = list(current_agents)
    if first_load:
        return []
    previous_edges = {
        agent.identity: _waiter_follow_edges(agent) for agent in previous_agents
    }
    current_edges = {
        agent.identity: _waiter_follow_edges(agent) for agent in current_list
    }
    names = {agent.identity: _waiter_name(agent) for agent in current_list}
    messages = epic_follow_toast_messages(previous_edges, current_edges, names)
    if callable(notify):
        for message in messages:
            notify(message)  # type: ignore[operator]
    return messages


__all__ = [
    "announce_epic_follow_transitions",
    "epic_follow_toast_messages",
]

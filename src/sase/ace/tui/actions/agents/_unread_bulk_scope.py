"""Shared bulk-ack scope and time-bound undo window.

Phase ``bulk-ack-scope-and-undo`` (epic ``sase-1d7``): "all" for ``,u``
means every loaded unread terminal agent node across all Agents tabs,
including collapsed clans and tribes and off-tab query rows. This module
holds the one predicate and target collector shared by
``_toggle_all_unread_done_agents_read`` and the header unread count (see
``_agent_info_metrics``), so the toast count always equals the header
count, plus the named undo-window constant both the state mixin and the
leader toast render from.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ...models.agent_nodes import is_agents_tab_agent_node
from ...models.agent_status import is_unread_completed_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

#: How long after a bulk mark ``,u`` restores the same identities instead
#: of reporting nothing unread. Rendered into the mark toast; the leader
#: handler and the state mixin both read this constant.
BULK_READ_UNDO_WINDOW_SECONDS = 10.0


def is_bulk_ack_unread_target(
    agent: Agent,
    unread_ids: set[tuple[AgentType, str, str | None]]
    | frozenset[tuple[AgentType, str, str | None]],
) -> bool:
    """Return True when *agent* is one bulk-ack target row.

    The same predicate gates the bulk-ack target set, the header unread
    count, and the unread jump candidates: a loaded Agents-tab agent node
    whose identity is unread and whose status is terminal. Clan
    containers, session members, workflow children, monitors, gates, and
    named procs are never targets (see :func:`is_agents_tab_agent_node`).
    """
    return (
        is_agents_tab_agent_node(agent)
        and agent.identity in unread_ids
        and is_unread_completed_status(agent.status)
    )


def bulk_ack_roster_universe(owner: Any) -> list[Agent]:
    """Return every loaded row the bulk-ack scope covers, deduplicated.

    The union of the tab-independent query result, the unfiltered roster
    (collapsed clan/tribe members live here), and the active-tab scoped
    roster, in that order, deduplicated by identity. Read-only: collecting
    targets never expands a panel or moves the tab scope.
    """
    seen: set[tuple[AgentType, str, str | None]] = set()
    universe: list[Agent] = []
    for source in (
        getattr(owner, "_agents_query_result", None),
        getattr(owner, "_agents_with_children", None),
        getattr(owner, "_agents", None),
    ):
        if not source:
            continue
        for agent in source:
            try:
                identity = agent.identity
            except AttributeError:
                continue
            if identity in seen:
                continue
            seen.add(identity)
            universe.append(agent)
    return universe


def bulk_unread_ack_targets(owner: Any) -> list[Agent]:
    """Return every loaded unread terminal agent node across all tabs.

    Collapsed clan/tribe members and off-tab query rows are included;
    collecting them never expands a panel.
    """
    unread_ids: set[tuple[AgentType, str, str | None]] = (
        getattr(owner, "_unread_completed_agent_ids", None) or set()
    )
    if not unread_ids:
        return []
    return [
        agent
        for agent in bulk_ack_roster_universe(owner)
        if is_bulk_ack_unread_target(agent, unread_ids)
    ]


def bulk_read_undo_window_open(
    armed_at: float | None,
    *,
    now: float | None = None,
) -> bool:
    """Return True when a bulk-read undo armed at *armed_at* still applies.

    A ``None`` timestamp means the undo was never armed (or predates the
    window): fail closed so a stale snapshot can never resurrect rows.
    """
    if armed_at is None:
        return False
    if now is None:
        now = time.monotonic()
    return 0 <= now - armed_at <= BULK_READ_UNDO_WINDOW_SECONDS


__all__ = [
    "BULK_READ_UNDO_WINDOW_SECONDS",
    "bulk_ack_roster_universe",
    "bulk_read_undo_window_open",
    "bulk_unread_ack_targets",
    "is_bulk_ack_unread_target",
]

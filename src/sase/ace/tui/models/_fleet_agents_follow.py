"""Follow-state matching and de-duplication for fleet-agent rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.dispatch.follow_store import FollowStoreSnapshot

from ._fleet_agents_scalars import locator_id
from .agent import Agent, AgentType


def active_follow_state(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[frozenset[str], frozenset[str]]:
    if snapshot is None:
        return frozenset(), frozenset()
    locator_ids = []
    for record in snapshot.active_records:
        locator = record.get("logical_locator")
        if isinstance(locator, Mapping):
            locator_ids.append(locator_id(locator))
    return snapshot.active_logical_keys, frozenset(locator_ids)


def summary_followed(
    agent: Agent,
    active_keys: frozenset[str],
    active_locator_ids: frozenset[str],
) -> bool:
    if agent.fleet_logical_key and agent.fleet_logical_key in active_keys:
        return True
    if agent.fleet_logical_locator:
        return locator_id(agent.fleet_logical_locator) in active_locator_ids
    return False


def dedupe_rows(rows: Sequence[Agent]) -> list[Agent]:
    deduped: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for row in rows:
        if row.identity in seen:
            continue
        deduped.append(row)
        seen.add(row.identity)
    return deduped

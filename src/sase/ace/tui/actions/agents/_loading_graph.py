"""Worker ownership for prepared Agents-tab apply snapshots.

``PreparedApplySnapshot`` is frozen, but that only freezes the snapshot
fields. The ``Agent`` rows in ``cached_agents_with_children`` and
``capacity_agents_with_children`` remain the live UI graph unless this
boundary copies them first.

Call this before any mutating preparation (incomplete merge, status
overrides, relationship rebuild, runner-slot annotation, or proc-shell
carryover that will be published). Incoming loader rows that are not in
the live graph stay as-is so the current worker keeps exclusive ownership
of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ...models._agent_graph import adopt_agents, copy_agent_graph
from ...models.agent import Agent
from ._loading_compute_types import PreparedApplyData, PreparedApplySnapshot

__all__ = [
    "adopt_prepared_apply_data",
    "own_prepared_apply_snapshot",
]


def own_prepared_apply_snapshot(
    snapshot: PreparedApplySnapshot,
) -> tuple[PreparedApplySnapshot, dict[int, Agent]]:
    """Return a snapshot whose cached row graphs are worker-owned copies.

    Uses one memo across the visible, capacity, and fleet rosters so a row that
    appears in several stays a single object in the detached graph. The worker
    projects the fleet rows into the roster, and that projection writes tree
    links onto them, so they must not alias the live fleet rows.
    """
    memo: dict[int, Agent] = {}
    owned = replace(
        snapshot,
        cached_agents_with_children=copy_agent_graph(
            snapshot.cached_agents_with_children,
            memo,
        ),
        capacity_agents_with_children=copy_agent_graph(
            snapshot.capacity_agents_with_children,
            memo,
        ),
        fleet_rows=tuple(copy_agent_graph(snapshot.fleet_rows, memo)),
    )
    return owned, memo


def adopt_prepared_apply_data(
    prep: PreparedApplyData,
    memo: Mapping[int, Agent],
) -> PreparedApplyData:
    """Rewrite *prep* lists so live cached rows are replaced by detached copies."""
    prep.filtered_agents = adopt_agents(prep.filtered_agents, memo)
    prep.hideable_agents = adopt_agents(prep.hideable_agents, memo)
    prep.capacity_agents = adopt_agents(prep.capacity_agents, memo)
    prep.dismissed_agent_objects = adopt_agents(prep.dismissed_agent_objects, memo)
    return prep

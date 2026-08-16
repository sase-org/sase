"""Pure agent-node-relative projection of agent neighbors."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .agent import Agent
from .agent_hoods import (
    AgentIdentity,
    AgentNeighborIndex,
    AgentNeighborRow,
    agent_name_key,
)

type NeighborRelation = Literal["ancestor", "descendant", "neighbor"]


@dataclass(frozen=True, slots=True)
class LaneNeighborRow:
    """One related row in an agent node's shared modal/panel projection."""

    agent: Agent
    relation: NeighborRelation
    group_label: str
    label_prefix: str
    is_prospective: bool
    is_dismissed: bool
    hood: str = ""
    index_row: AgentNeighborRow | None = None


@dataclass(frozen=True, slots=True)
class SaseAgentNeighborProjection:
    """Ordered neighbor rows for one agent-node-owning sase agent."""

    lane_identity: AgentIdentity
    rows: tuple[LaneNeighborRow, ...]
    suppressed_lane_member_count: int

    @property
    def is_empty(self) -> bool:
        """Return whether the projection has no visible related rows."""
        return not self.rows


def build_sase_agent_neighbor_projection(
    *,
    lane_identity: AgentIdentity,
    lane_name: str | None,
    lane_row_names: Collection[str] = (),
    index: AgentNeighborIndex,
    dismissed_descendants: Sequence[Agent] = (),
    suppressed_identities: Collection[AgentIdentity] = (),
    hood_labels: Mapping[str, str] | None = None,
) -> SaseAgentNeighborProjection:
    """Build the shared ordered neighbor projection for one sase agent."""
    rows: list[LaneNeighborRow] = []

    for target in index.ancestor_targets_for(lane_identity):
        rows.append(
            LaneNeighborRow(
                agent=target.agent,
                relation="ancestor",
                group_label="ancestors",
                label_prefix="",
                is_prospective=target.is_prospective,
                is_dismissed=False,
                index_row=target,
            )
        )

    descendant_items: list[tuple[str, bool, Agent, AgentNeighborRow | None]] = []
    for target in index.descendant_targets_for(lane_identity):
        key = agent_name_key(target.agent)
        if key is not None:
            descendant_items.append((key, False, target.agent, target))
    for agent in dismissed_descendants:
        key = agent_name_key(agent)
        if key is not None:
            descendant_items.append((key, True, agent, None))

    for _key, is_dismissed, agent, descendant_target in sorted(
        descendant_items,
        key=lambda item: (
            item[0],
            item[1],
            (item[2].display_name or "").casefold(),
        ),
    ):
        rows.append(
            LaneNeighborRow(
                agent=agent,
                relation="descendant",
                group_label="descendants",
                label_prefix=lane_name or "",
                is_prospective=(
                    descendant_target.is_prospective
                    if descendant_target is not None
                    else False
                ),
                is_dismissed=is_dismissed,
                index_row=descendant_target,
            )
        )

    labels = hood_labels or {}
    for hood, targets in index.hood_neighbor_target_groups_for(lane_identity):
        hood_label = labels.get(hood, hood)
        for target in targets:
            rows.append(
                LaneNeighborRow(
                    agent=target.agent,
                    relation="neighbor",
                    group_label=f"{hood_label} hood",
                    label_prefix=hood_label,
                    is_prospective=target.is_prospective,
                    is_dismissed=False,
                    hood=hood_label,
                    index_row=target,
                )
            )

    suppressed = set(suppressed_identities)
    lane_keys = {name.casefold() for name in lane_row_names if name}
    if lane_name:
        lane_keys.add(lane_name.casefold())
    retained: list[LaneNeighborRow] = []
    suppressed_count = 0
    for row in rows:
        if (
            row.agent.identity == lane_identity
            or agent_name_key(row.agent) in lane_keys
        ):
            # A lane is never its own neighbor. An expanded family renders its
            # root member as a second row with a synthetic identity, so drop by
            # name key too rather than trusting identity alone. ``lane_row_names``
            # carries the owner's raw ``--<suffix>`` name, which is how that
            # duplicate root-member row is keyed once the lane itself keys on
            # the bare family base.
            continue
        if row.agent.identity in suppressed:
            suppressed_count += 1
        else:
            retained.append(row)

    return SaseAgentNeighborProjection(
        lane_identity=lane_identity,
        rows=tuple(retained),
        suppressed_lane_member_count=suppressed_count,
    )


__all__ = [
    "SaseAgentNeighborProjection",
    "LaneNeighborRow",
    "NeighborRelation",
    "build_sase_agent_neighbor_projection",
]

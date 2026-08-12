"""Fold-aware lane-neighbor rendering for agent prompt panels."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime

from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket

from ...models.agent_hoods import AgentIdentity
from ...models.agent_lane_neighbors import (
    AgentLaneNeighborProjection,
    LaneNeighborRow,
)
from ...models.fold_scale import (
    FoldScale,
    effective_fold_level,
    fold_scale_position,
)
from ...models.fold_state import FoldLevel
from ._agent_display_content import get_phase_label
from ._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from ._member_roster_digest import agent_roster_digest, agent_roster_duration

NEIGHBORS_SECTION_ID = "neighbors"
NEIGHBORS_IDENTITY_COLOR = "#00D7AF"
NEIGHBORS_ROSTER_TITLE = "NEIGHBORS"
NEIGHBORS_FIRST_LEVEL_LIMIT = 3
NEIGHBORS_MID_LEVEL_LIMIT = 10


def neighbor_entry_limit(level: FoldLevel, scale: FoldScale) -> int | None:
    """Return the positional lane-neighbor row limit at ``level``."""
    position, size = fold_scale_position(level, scale)
    if position == 1:
        return NEIGHBORS_FIRST_LEVEL_LIMIT
    if position == size:
        return None
    return NEIGHBORS_MID_LEVEL_LIMIT


def _neighbor_roster_entries(
    rows: Sequence[LaneNeighborRow],
    *,
    unread_agent_ids: Collection[AgentIdentity] = (),
    marked_identities: Collection[AgentIdentity] = (),
    now: datetime | None = None,
) -> tuple[MemberRosterEntry, ...]:
    """Adapt lane-neighbor rows into shared roster entries."""
    entries: list[MemberRosterEntry] = []
    for row in rows:
        agent = row.agent
        phase_label = get_phase_label(agent)
        kind = "agent" if phase_label == "AGENT" else phase_label
        entries.append(
            MemberRosterEntry(
                identity=agent.identity,
                presented_name=(
                    agent.presented_identity_name
                    or agent.presented_agent_name
                    or agent.display_name
                ),
                label=_neighbor_label(row),
                kind=kind,
                status=agent.display_status,
                effective_bucket=agent_status_bucket(agent),
                model=agent.model or "default",
                duration=agent_roster_duration(agent, now=now),
                digest=agent_roster_digest(
                    agent,
                    extra_annotations=("folded",) if row.is_prospective else (),
                ),
                group_label=row.group_label,
                is_dismissed=row.is_dismissed,
                is_marked=agent.identity in marked_identities,
                is_unread=agent.identity in unread_agent_ids,
                target_role="dismissed" if row.is_dismissed else None,
            )
        )
    return tuple(entries)


def append_lane_neighbors_section(
    text: Text,
    *,
    projection: AgentLaneNeighborProjection,
    panel_level: FoldLevel,
    scale: FoldScale,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    numbering: MemberJumpNumbering | None = None,
    unread_agent_ids: Collection[AgentIdentity] = (),
    marked_identities: Collection[AgentIdentity] = (),
    now: datetime | None = None,
) -> MemberJumpMap | None:
    """Append the lane's NEIGHBORS roster and return its jump map."""
    if projection.is_empty:
        return None

    overrides = section_fold_overrides or {}
    neighbors_level = effective_fold_level(
        overrides.get(NEIGHBORS_SECTION_ID, panel_level),
        scale,
    )
    entry_limit = neighbor_entry_limit(neighbors_level, scale)
    entries = _neighbor_roster_entries(
        projection.rows,
        unread_agent_ids=unread_agent_ids,
        marked_identities=marked_identities,
        now=now,
    )
    if numbering is None:
        shown_count = (
            len(entries) if entry_limit is None else min(len(entries), entry_limit)
        )
        numbering = MemberJumpNumbering(total=shown_count)
    suppressed_count = projection.suppressed_lane_member_count
    return append_member_roster(
        text,
        container_identity=projection.lane_identity,
        entries=entries,
        title=NEIGHBORS_ROSTER_TITLE,
        accent=NEIGHBORS_IDENTITY_COLOR,
        panel_level=panel_level,
        section_fold_overrides=overrides,
        fold_scale=scale,
        section_id=NEIGHBORS_SECTION_ID,
        member_anchor_prefix="neighbor:",
        numbering=numbering,
        entry_limit=entry_limit,
        hidden_tail_label="neighbors",
        hidden_tail_hint="zz / za to show more",
        extra_tail=(
            f"… +{suppressed_count} also listed under FAMILY MEMBERS"
            if suppressed_count
            else None
        ),
        target_role="neighbor",
    )


def _neighbor_label(row: LaneNeighborRow) -> str:
    agent = row.agent
    presented_name = (
        agent.presented_agent_name
        or agent.presented_identity_name
        or agent.display_name
    )
    prefix = row.label_prefix
    if prefix and presented_name.startswith(prefix):
        suffix = presented_name[len(prefix) :]
        if suffix.startswith((".", "--")):
            return suffix
    return presented_name


__all__ = [
    "NEIGHBORS_FIRST_LEVEL_LIMIT",
    "NEIGHBORS_IDENTITY_COLOR",
    "NEIGHBORS_MID_LEVEL_LIMIT",
    "NEIGHBORS_ROSTER_TITLE",
    "NEIGHBORS_SECTION_ID",
    "append_lane_neighbors_section",
    "neighbor_entry_limit",
]

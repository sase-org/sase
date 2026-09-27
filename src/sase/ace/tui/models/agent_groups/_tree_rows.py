"""Banner and agent row records for the grouped agent tree."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GroupRow:
    """A banner row in the grouped agent tree."""

    # 0 = project/date/status bucket. Deeper levels are structural
    # descendants: Patch, BY_DATE subgroup, name-root, or dotted
    # name-prefix subgroup depending on the active layout.
    level: int
    group_key: tuple[str, ...]
    agent_indices: tuple[int, ...]
    is_collapsed: bool = False
    has_child_groups: bool = False


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One row in the rendered tree — either a banner or an agent."""

    kind: str  # "group" or "agent"
    group: GroupRow | None = None
    agent_idx: int | None = None

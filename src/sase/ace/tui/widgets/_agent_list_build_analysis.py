"""Pure tree and row analysis helpers for AgentList builds."""

from __future__ import annotations

from ..models._agent_tree import agent_parent_fold_key
from ..models.agent import Agent
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
    NO_HOUR_LABEL,
    TreeEntry,
)
from ._agent_list_styling import (
    _BANNER_ROW,
    _PATCH_BANNER_RULE_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
)


def visible_agent_indices(tree: list[TreeEntry]) -> set[int]:
    """Return the agent indices *tree* actually emits as rows.

    Agents inside a collapsed group are absent: the tree walk skips them,
    so they must not influence row measurement or per-row render state.
    """
    return {
        entry.agent_idx
        for entry in tree
        if entry.kind != "group" and entry.agent_idx is not None
    }


def compute_visible_parents(
    agents: list[Agent],
) -> tuple[set[str], set[str]]:
    """Return ``(parents_with_visible_children, fully_expanded_parents)``."""
    parents_with_visible_children: set[str] = set()
    fully_expanded_parents: set[str] = set()
    for agent in agents:
        parent_key = agent_parent_fold_key(agent)
        if parent_key is not None:
            parents_with_visible_children.add(parent_key)
            if agent.is_hidden_step:
                fully_expanded_parents.add(parent_key)
    return parents_with_visible_children, fully_expanded_parents


def compute_tier_styles(
    tree: list[TreeEntry],
    *,
    panel_uses_cs: bool,
    mode: GroupingMode = GroupingMode.STANDARD,
) -> tuple[dict[int, tuple[str, ...]], list[tuple[str, ...]]]:
    """Walk *tree* and compute per-row tier-guide gutter styles.

    Returns ``(agent_tier_styles, banner_tier_styles)``:

    * ``agent_tier_styles[i]`` - the gutter for ``agents[i]``'s row.
    * ``banner_tier_styles[seq]`` - the gutter for the ``seq``-th
      banner emitted, in tree order.

    The gutter for a row is the list of visible ancestor tier styles that
    contribute a visible guide segment.  L0 (project / bucket) banners always
    contribute.  Middle-tier banners contribute the cooler Patch
    rule style: STANDARD L1 Patch banners, real BY_DATE L1 subgroup
    banners, BY_MACHINE L1 status subgroup banners (every status label is
    real, so all contribute), and name-root banners that own dotted-name
    prefix subgroups.  Terminal branch banners and synthetic ``(no time)``
    buckets do not add a descendant tier.  Order is outermost first.
    """
    agent_styles: dict[int, tuple[str, ...]] = {}
    banner_styles: list[tuple[str, ...]] = []

    def is_stack_ancestor(
        parent_key: tuple[str, ...], child_key: tuple[str, ...]
    ) -> bool:
        return (
            len(parent_key) < len(child_key)
            and child_key[: len(parent_key)] == parent_key
        )

    def descendant_style_for(group: GroupRow) -> str | None:
        if group.level == 0:
            return _PROJECT_BANNER_RULE_STYLE
        if group.level == 1 and panel_uses_cs and len(group.group_key) == 2:
            return _PATCH_BANNER_RULE_STYLE
        if (
            group.level == 1
            and mode is GroupingMode.BY_DATE
            and group.group_key[-1] != NO_HOUR_LABEL
        ):
            return _PATCH_BANNER_RULE_STYLE
        if group.level == 1 and mode is GroupingMode.BY_MACHINE:
            return _PATCH_BANNER_RULE_STYLE
        if group.has_child_groups:
            return _PATCH_BANNER_RULE_STYLE
        return None

    active: list[tuple[tuple[str, ...], str]] = []
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            g = entry.group
            while active and not is_stack_ancestor(active[-1][0], g.group_key):
                active.pop()
            banner_styles.append(tuple(style for _, style in active))
            descendant_style = descendant_style_for(g)
            if descendant_style is not None:
                active.append((g.group_key, descendant_style))
            continue
        if entry.agent_idx is not None:
            agent_styles[entry.agent_idx] = tuple(style for _, style in active)
    return agent_styles, banner_styles


def resolve_row(
    option_index: int,
    row_entries: list[tuple[int, int | None]],
    banner_at_row: dict[int, GroupRow],
) -> tuple[int, int | None, tuple[str, ...] | None]:
    """Translate a raw OptionList row index to selection state.

    Returns ``(agent_idx, attempt_number, group_key)``.  When a
    selectable (collapsed) banner row is hit the ``group_key`` is the
    banner's :attr:`GroupRow.group_key` and ``agent_idx`` points at
    the first agent in the group so the detail panel still has
    something to show.  When a banner is non-selectable (its group
    is expanded) the row resolves to the next agent row.
    """
    if 0 <= option_index < len(row_entries):
        entry = row_entries[option_index]
        banner = banner_at_row.get(option_index)
        if banner is not None:
            first = banner.agent_indices[0] if banner.agent_indices else 0
            return (first, None, banner.group_key)
        if entry[0] == _BANNER_ROW:
            for j in range(option_index + 1, len(row_entries)):
                nxt = row_entries[j]
                if nxt[0] != _BANNER_ROW:
                    return (nxt[0], nxt[1], None)
            for j in range(option_index - 1, -1, -1):
                prv = row_entries[j]
                if prv[0] != _BANNER_ROW:
                    return (prv[0], prv[1], None)
            return (0, None, None)
        return (entry[0], entry[1], None)
    return (option_index, None, None)


__all__ = [
    "compute_tier_styles",
    "compute_visible_parents",
    "resolve_row",
    "visible_agent_indices",
]

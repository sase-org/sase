"""Fold-state filtering for agent lists."""

from .agent import Agent
from ._agent_tree import agent_fold_key
from .fold_state import FoldLevel, FoldStateManager


def filter_agents_by_fold_state(
    agents: list[Agent],
    fold_manager: FoldStateManager,
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Filter agent list based on fold state of workflow parents.

    Scans the flat agent list (children interleaved after parents) and
    filters children based on the fold level of their parent workflow.

    Args:
        agents: Full agent list with children after parents.
        fold_manager: Manager tracking fold state per workflow.

    Returns:
        Tuple of (filtered_agents, fold_counts) where fold_counts maps
        workflow raw_suffix -> (non_hidden_child_count, hidden_child_count).
    """
    # First pass: collect ordinary children and synthetic-clan descendants.
    fold_counts: dict[str, tuple[int, int]] = {}
    children_by_parent: dict[str, list[Agent]] = {}
    present_parent_keys = {
        key
        for agent in agents
        if (key := agent_fold_key(agent)) is not None
        and (agent.is_clan_container or not agent.is_child_row)
    }

    for agent in agents:
        if agent.tree_parent_key:
            children_by_parent.setdefault(agent.tree_parent_key, []).append(agent)
            continue
        if agent.is_child_row and agent.parent_timestamp:
            parent_key = agent.parent_timestamp
            if parent_key not in present_parent_keys:
                continue
            if parent_key not in children_by_parent:
                children_by_parent[parent_key] = []
            children_by_parent[parent_key].append(agent)

    # Compute counts for each parent. Clan counts classify ordinary workflow
    # steps as visible at EXPANDED, while hidden steps and sequential-family
    # members remain gated on FULLY_EXPANDED at the third indentation level.
    for parent_key, children in children_by_parent.items():
        if parent_key.startswith("clan:"):
            hidden = sum(
                1
                for child in children
                if child.tree_depth > 1
                and (child.is_family_member_child or child.is_hidden_step)
            )
            non_hidden = len(children) - hidden
        else:
            non_hidden = sum(1 for c in children if not c.is_hidden_step)
            hidden = sum(1 for c in children if c.is_hidden_step)
        fold_counts[parent_key] = (non_hidden, hidden)

    # Identify parents whose children are ALL hidden (no visible work occurred)
    hidden_only_parents: set[str] = set()
    for parent_key, (non_hidden, hidden) in fold_counts.items():
        if non_hidden == 0 and hidden > 0:
            hidden_only_parents.add(parent_key)

    # Second pass: build filtered list
    result: list[Agent] = []
    for agent in agents:
        if agent.tree_parent_key:
            level = fold_manager.get(agent.tree_parent_key)
            if level == FoldLevel.COLLAPSED:
                continue
            if agent.tree_depth > 1:
                if agent.is_family_member_child:
                    if level != FoldLevel.FULLY_EXPANDED:
                        continue
                elif agent.is_hidden_step and level != FoldLevel.FULLY_EXPANDED:
                    continue
            result.append(agent)
            continue
        if agent.is_child_row and agent.parent_timestamp:
            parent_key = agent.parent_timestamp
            if parent_key not in present_parent_keys:
                continue
            if parent_key in hidden_only_parents:
                continue
            level = fold_manager.get(parent_key)
            if level == FoldLevel.COLLAPSED:
                continue
            if level == FoldLevel.EXPANDED and agent.is_hidden_step:
                continue
            # FULLY_EXPANDED: include all children
            result.append(agent)
        else:
            # Skip parents whose only children are hidden
            fold_key = agent_fold_key(agent)
            if fold_key in hidden_only_parents:
                continue
            result.append(agent)

    return result, fold_counts

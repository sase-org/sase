"""Fold-state filtering for agent lists."""

from .agent import Agent
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
    # First pass: collect children per parent and compute counts
    fold_counts: dict[str, tuple[int, int]] = {}
    children_by_parent: dict[str, list[Agent]] = {}

    for agent in agents:
        if agent.is_workflow_child and agent.parent_timestamp:
            parent_key = agent.parent_timestamp
            if parent_key not in children_by_parent:
                children_by_parent[parent_key] = []
            children_by_parent[parent_key].append(agent)

    # Compute counts for each parent
    for parent_key, children in children_by_parent.items():
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
        if agent.is_workflow_child and agent.parent_timestamp:
            parent_key = agent.parent_timestamp
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
            if agent.raw_suffix in hidden_only_parents:
                continue
            result.append(agent)

    return result, fold_counts

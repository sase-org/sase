"""Fold-state filtering for agent lists."""

from ._agent_tree import agent_fold_key, agent_parent_fold_key
from .agent import Agent
from .fold_state import FoldLevel, FoldStateManager


def filter_agents_by_fold_state(
    agents: list[Agent],
    fold_manager: FoldStateManager,
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Filter agents through every immediate ancestor's in-memory fold.

    ``fold_counts`` maps each owning row's fold key to its immediate ordinary
    and hidden child counts. Synthetic clan folds own only their direct
    members; each member independently owns its workflow/family children.
    """
    owners_by_key: dict[str, Agent] = {}
    for agent in agents:
        key = agent_fold_key(agent)
        if key is not None and not agent.is_child_row:
            owners_by_key[key] = agent
    children_by_parent: dict[str, list[Agent]] = {}
    for agent in agents:
        parent_key = agent_parent_fold_key(agent)
        if parent_key is None or parent_key not in owners_by_key:
            continue
        children_by_parent.setdefault(parent_key, []).append(agent)

    fold_counts: dict[str, tuple[int, int]] = {}
    for parent_key, children in children_by_parent.items():
        if parent_key.startswith("clan:"):
            # The outer clan fold is binary: every direct member is ordinary.
            fold_counts[parent_key] = (len(children), 0)
            continue
        hidden = sum(1 for child in children if child.is_hidden_step)
        fold_counts[parent_key] = (len(children) - hidden, hidden)

    # Historical non-clan workflows containing only internal steps stay out of
    # the Agents tab. Clan members remain visible as direct clan members even
    # when all of their own workflow children are hidden.
    hidden_only_parents = {
        parent_key
        for parent_key, (ordinary, hidden) in fold_counts.items()
        if ordinary == 0
        and hidden > 0
        and owners_by_key[parent_key].tree_parent_key is None
    }

    visibility: dict[int, bool] = {}

    def is_visible(agent: Agent, visiting: set[int]) -> bool:
        agent_id = id(agent)
        if agent_id in visibility:
            return visibility[agent_id]
        if agent_id in visiting:
            visibility[agent_id] = False
            return False

        own_key = agent_fold_key(agent)
        if own_key in hidden_only_parents:
            visibility[agent_id] = False
            return False

        parent_key = agent_parent_fold_key(agent)
        if parent_key is None:
            visibility[agent_id] = True
            return True
        parent = owners_by_key.get(parent_key)
        if parent is None:
            visibility[agent_id] = False
            return False

        visiting.add(agent_id)
        parent_visible = is_visible(parent, visiting)
        visiting.discard(agent_id)
        if not parent_visible:
            visibility[agent_id] = False
            return False

        level = fold_manager.get(parent_key)
        if level == FoldLevel.COLLAPSED:
            visibility[agent_id] = False
            return False
        if (
            not parent_key.startswith("clan:")
            and agent.is_hidden_step
            and level != FoldLevel.FULLY_EXPANDED
        ):
            visibility[agent_id] = False
            return False

        visibility[agent_id] = True
        return True

    return [agent for agent in agents if is_visible(agent, set())], fold_counts

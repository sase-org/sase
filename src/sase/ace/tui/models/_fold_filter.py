"""Fold-state filtering for agent lists."""

from ._agent_tree import agent_fold_key, agent_gating_fold_key, agent_parent_fold_key
from .agent import Agent
from .fold_state import FoldLevel, FoldStateManager


def filter_agents_by_fold_state(
    agents: list[Agent],
    fold_manager: FoldStateManager,
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Filter agents through every immediate ancestor's in-memory fold.

    ``fold_counts`` maps each owning row's fold key to the rows that fold
    reveals: its immediate ordinary and hidden child counts. Synthetic clan
    folds own only their direct members; each member independently owns its
    workflow/family children. A monitor row is instead counted and gated by
    its *gating* fold key (see :func:`agent_gating_fold_key`) -- the agent
    family or workflow that reveals it -- rather than its immediate starter,
    so a mid-family starter never owns a monitor's fold.
    """
    owners_by_key: dict[str, Agent] = {}
    for agent in agents:
        key = agent_fold_key(agent)
        if key is None:
            continue
        existing = owners_by_key.get(key)
        if existing is not None and (not existing.is_child_row or agent.is_child_row):
            continue
        if agent.is_child_row and agent_parent_fold_key(agent) == key:
            # Legacy workflow children repeat their parent's suffix. They
            # alias the parent fold and must not own it, including when
            # that parent is absent.
            continue
        # A non-child row wins a repeated key. Uniquely-keyed child rows
        # still register so a grandchild can resolve its parent.
        owners_by_key[key] = agent
    children_by_parent: dict[str, list[Agent]] = {}
    for agent in agents:
        parent_key = agent_gating_fold_key(agent, owners_by_key)
        if parent_key is None or parent_key not in owners_by_key:
            continue
        if agent.is_monitor and parent_key.startswith("clan:"):
            # A clan's counts are direct-member counts and clan_members
            # already excludes monitor rows. A monitor whose gating chain
            # collapses onto the clan fold (a malformed/disk-shaped
            # projection with no loaded family root) stays out too.
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

        # The hidden-step/FULLY_EXPANDED rule below stays keyed on the
        # immediate parent; a monitor is never a hidden step, so only the
        # COLLAPSED gate needs its own key for monitor rows.
        level = fold_manager.get(parent_key)
        if agent.is_monitor:
            gating_key = agent_gating_fold_key(agent, owners_by_key)
            gating_level = None if gating_key is None else fold_manager.get(gating_key)
            # An unresolvable gating chain (a malformed projection) falls
            # back to visible-with-parent rather than hiding the row.
            if gating_level == FoldLevel.COLLAPSED:
                visibility[agent_id] = False
                return False
        elif level == FoldLevel.COLLAPSED:
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

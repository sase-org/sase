"""Fold-state filtering for agent lists."""

from ._agent_tree import agent_fold_key, agent_gating_fold_key, agent_parent_fold_key
from .agent import Agent
from .fold_state import FoldLevel, FoldStateManager


def filter_agents_by_fold_state(
    agents: list[Agent],
    fold_manager: FoldStateManager,
    *,
    fold_keys: dict[int, str | None] | None = None,
    parent_keys: dict[int, str | None] | None = None,
    hidden_steps: set[int] | frozenset[int] | None = None,
    is_monitor_map: dict[int, bool] | None = None,
    is_gate_map: dict[int, bool] | None = None,
    is_child_row_map: dict[int, bool] | None = None,
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Filter agents through every immediate ancestor's in-memory fold.

    ``fold_counts`` maps each owning row's fold key to the rows that fold
    reveals: its immediate ordinary and hidden child counts. Synthetic clan
    folds own only their direct members; each member independently owns its
    workflow/session children. A session shell row is instead counted and gated by
    its *gating* fold key (see :func:`agent_gating_fold_key`) -- the agent
    agent session or workflow that reveals it -- rather than its immediate starter,
    so a mid-agent session starter never owns a shell's fold.

    The optional *fold_keys*, *parent_keys*, and *hidden_steps* carry one
    per-open read of :func:`agent_fold_key`, :func:`agent_parent_fold_key`,
    and ``is_hidden_step`` keyed by ``id(agent)`` for the same roster, so
    batch callers skip re-deriving those predicates once per pass. The
    optional *is_monitor_map*, *is_gate_map*, and *is_child_row_map* carry
    the same per-open role booleans so the snapshot builder pays for each
    plan-chain role parse once instead of once per pass. Results are
    identical; any agent missing from the tables falls back to a direct
    read.
    """

    def _fold_key(agent: Agent, agent_id: int) -> str | None:
        if fold_keys is not None and agent_id in fold_keys:
            return fold_keys[agent_id]
        return agent_fold_key(agent)

    def _parent_key(agent: Agent, agent_id: int) -> str | None:
        if parent_keys is not None and agent_id in parent_keys:
            return parent_keys[agent_id]
        return agent_parent_fold_key(agent)

    def _is_hidden(agent: Agent, agent_id: int) -> bool:
        if hidden_steps is not None:
            return agent_id in hidden_steps
        return agent.is_hidden_step

    def _is_monitor(agent: Agent, agent_id: int) -> bool:
        if is_monitor_map is not None and agent_id in is_monitor_map:
            return is_monitor_map[agent_id]
        return agent.is_monitor

    def _is_gate(agent: Agent, agent_id: int) -> bool:
        if is_gate_map is not None and agent_id in is_gate_map:
            return is_gate_map[agent_id]
        return agent.is_gate

    def _is_child_row(agent: Agent, agent_id: int) -> bool:
        if is_child_row_map is not None and agent_id in is_child_row_map:
            return is_child_row_map[agent_id]
        return agent.is_child_row

    def _gating_key(agent: Agent, agent_id: int) -> str | None:
        if (
            is_monitor_map is not None
            and is_gate_map is not None
            and is_child_row_map is not None
            and parent_keys is not None
            and agent_id in is_monitor_map
            and agent_id in is_gate_map
        ):
            if not (_is_monitor(agent, agent_id) or _is_gate(agent, agent_id)):
                return _parent_key(agent, agent_id)
        return agent_gating_fold_key(agent, owners_by_key)

    owners_by_key: dict[str, Agent] = {}
    owners_child_row: dict[str, bool] = {}
    for agent in agents:
        agent_id = id(agent)
        key = _fold_key(agent, agent_id)
        if key is None:
            continue
        existing = owners_by_key.get(key)
        if existing is not None and (
            not owners_child_row.get(key, existing.is_child_row)
            or _is_child_row(agent, agent_id)
        ):
            continue
        if _is_child_row(agent, agent_id) and _parent_key(agent, agent_id) == key:
            # Legacy workflow children repeat their parent's suffix. They
            # alias the parent fold and must not own it, including when
            # that parent is absent.
            continue
        # A non-child row wins a repeated key. Uniquely-keyed child rows
        # still register so a grandchild can resolve its parent.
        owners_by_key[key] = agent
        owners_child_row[key] = _is_child_row(agent, agent_id)
    children_by_parent: dict[str, list[Agent]] = {}
    for agent in agents:
        agent_id = id(agent)
        if _is_monitor(agent, agent_id) or _is_gate(agent, agent_id):
            parent_key = _gating_key(agent, agent_id)
        else:
            # Non-shell rows are gated by their immediate parent, which the
            # facet table already holds.
            parent_key = _parent_key(agent, agent_id)
        if parent_key is None or parent_key not in owners_by_key:
            continue
        if (
            _is_monitor(agent, agent_id) or _is_gate(agent, agent_id)
        ) and parent_key.startswith("clan:"):
            # A clan's counts are direct-member counts and clan_members
            # already excludes session shell rows. A shell whose gating chain
            # collapses onto the clan fold (a malformed/disk-shaped
            # projection with no loaded session root) stays out too.
            continue
        children_by_parent.setdefault(parent_key, []).append(agent)

    fold_counts: dict[str, tuple[int, int]] = {}
    for parent_key, children in children_by_parent.items():
        if parent_key.startswith("clan:"):
            # The outer clan fold is binary: every direct member is ordinary.
            fold_counts[parent_key] = (len(children), 0)
            continue
        hidden = sum(1 for child in children if _is_hidden(child, id(child)))
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

        own_key = _fold_key(agent, agent_id)
        if own_key in hidden_only_parents:
            visibility[agent_id] = False
            return False

        parent_key = _parent_key(agent, agent_id)
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
        # immediate parent; a session shell is never a hidden step, so only the
        # COLLAPSED gate needs its own key for shell rows.
        level = fold_manager.get(parent_key)
        if _is_monitor(agent, agent_id) or _is_gate(agent, agent_id):
            gating_key = _gating_key(agent, agent_id)
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
            and _is_hidden(agent, agent_id)
            and level != FoldLevel.FULLY_EXPANDED
        ):
            visibility[agent_id] = False
            return False

        visibility[agent_id] = True
        return True

    return [agent for agent in agents if is_visible(agent, set())], fold_counts

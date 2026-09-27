"""Fold keys, tree depth, and titles for the agent tree projection."""

from __future__ import annotations

from collections.abc import Mapping

from .agent import Agent
from .agent_named_procs import named_proc_command_title


def clan_fold_key(clan_name: str, generation: str | None = None) -> str:
    """Return the stable :class:`FoldStateManager` key for a clan row."""
    suffix = f":{generation}" if generation else ""
    return f"clan:{clan_name}{suffix}"


def agent_fold_key(agent: Agent) -> str | None:
    """Return the fold key owned by *agent* for its visible descendants."""
    if agent.is_clan_container and agent.agent_clan:
        return clan_fold_key(agent.agent_clan, agent.agent_clan_generation)
    if agent.raw_suffix:
        return agent.raw_suffix
    return None


def agent_parent_fold_key(agent: Agent) -> str | None:
    """Return the fold key controlling *agent* as an immediate child row."""
    if agent.tree_parent_key:
        return agent.tree_parent_key
    # ``is_child_row`` is exactly ``parent_workflow/parent_timestamp is not
    # None`` (see :meth:`child_linkage`), so a set timestamp already implies
    # the child row and no linkage call is needed on this hot path.
    return agent.parent_timestamp or None


def agent_gating_fold_key(
    agent: Agent, owners_by_key: Mapping[str, Agent]
) -> str | None:
    """Return the fold key whose expansion reveals *agent*.

    Non-turn rows are gated by their own immediate parent, same as
    :func:`agent_parent_fold_key`. A session turn row instead climbs its
    immediate-parent chain to the nearest ancestor that is not itself a
    child row -- the agent session/workflow container whose fold actually reveals
    the turn, skipping past any mid-agent session starter that owns no fold of
    its own. Returns ``None`` when a link in that chain is missing or the
    chain does not resolve within the number of known fold owners.
    """
    if not (agent.is_monitor or agent.is_gate):
        return agent_parent_fold_key(agent)

    current: Agent = agent
    visited: set[int] = set()
    for _ in range(len(owners_by_key) + 1):
        parent_key = agent_parent_fold_key(current)
        if parent_key is None:
            return None
        owner = owners_by_key.get(parent_key)
        if owner is None:
            return None
        owner_id = id(owner)
        if owner_id in visited:
            return None
        visited.add(owner_id)
        if not owner.is_child_row:
            return parent_key
        current = owner
    return None


def agent_tree_depth(agent: Agent) -> int:
    """Return an Agents-tab indentation depth without reading external state."""
    if agent.tree_depth > 0:
        return agent.tree_depth
    return 1 if agent.is_child_row else 0


def agent_is_tree_child(agent: Agent) -> bool:
    """Return whether *agent* nests beneath another rendered agent row."""
    return agent_tree_depth(agent) > 0


_NAMED_WORKFLOW_STEP_TYPES = frozenset({"bash", "python"})


def agent_tree_title(agent: Agent) -> str | None:
    """Return the Agents-tab left-side title, or ``None`` for sase turns.

    Bash/python workflow steps use their step name as identity. Sase turns
    (agent session members, monitors, workflow ``agent`` steps) keep identity on the
    right-hand ``%id`` annotation. Clan containers, session containers, and
    standalone roots keep ``display_name``.
    """
    if agent.is_workflow_step_child and agent.step_type in _NAMED_WORKFLOW_STEP_TYPES:
        title = agent.step_name or agent.display_name
        return title or None
    if agent.is_named_proc:
        return agent.proc_label or named_proc_command_title(agent.proc_safe_preview)
    if _is_untitled_sase_turn(agent):
        return None
    return agent.display_name or None


def _is_untitled_sase_turn(agent: Agent) -> bool:
    if agent.is_clan_container or agent.is_agent_session_container_row:
        return False
    if agent.is_monitor or agent.is_gate:
        return True
    if agent.is_workflow_step_child and agent.step_type == "agent":
        return True
    return agent.is_agent_session_member_child

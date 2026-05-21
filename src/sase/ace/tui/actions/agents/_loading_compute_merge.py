"""Tier-1 patch merge logic for :func:`prepare_loaded_agents_apply_boundary`.

Splits off the post-history merge that folds an incoming Tier 1 partial
load on top of the cached complete-history view. Lives in its own
module so the entry point in :mod:`._loading_compute` stays small.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._loading_compute_types import PreparedApplyData, PreparedApplySnapshot
from ._loading_helpers import is_always_visible

if TYPE_CHECKING:
    from ...models import Agent


def _reattach_children_after_parent_dedup(
    agents_before_dedup: list[Agent],
    agents_after_dedup: list[Agent],
) -> list[Agent]:
    """Move children from removed same-PID parents to surviving parents."""
    after_ids = {id(agent) for agent in agents_after_dedup}
    surviving_parent_by_pid: dict[int, Agent] = {}
    for agent in agents_after_dedup:
        if agent.pid is None or agent.raw_suffix is None or agent.is_workflow_child:
            continue
        surviving_parent_by_pid.setdefault(agent.pid, agent)

    replacement_suffix_by_removed_suffix: dict[str, str] = {}
    for agent in agents_before_dedup:
        if (
            id(agent) in after_ids
            or agent.pid is None
            or agent.raw_suffix is None
            or agent.is_workflow_child
        ):
            continue
        survivor = surviving_parent_by_pid.get(agent.pid)
        if (
            survivor is None
            or survivor.raw_suffix is None
            or survivor.raw_suffix == agent.raw_suffix
        ):
            continue
        replacement_suffix_by_removed_suffix[agent.raw_suffix] = survivor.raw_suffix

    if not replacement_suffix_by_removed_suffix:
        return agents_after_dedup

    reattached_ids: set[int] = set()
    for agent in agents_after_dedup:
        if not agent.is_workflow_child or agent.parent_timestamp is None:
            continue
        replacement_suffix = replacement_suffix_by_removed_suffix.get(
            agent.parent_timestamp
        )
        if replacement_suffix is None:
            continue
        agent.parent_timestamp = replacement_suffix
        reattached_ids.add(id(agent))

    if not reattached_ids:
        return agents_after_dedup

    children_by_parent: dict[str, list[Agent]] = {}
    roots_and_unchanged_children: list[Agent] = []
    for agent in agents_after_dedup:
        if id(agent) in reattached_ids and agent.parent_timestamp is not None:
            children_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
        else:
            roots_and_unchanged_children.append(agent)

    regrouped: list[Agent] = []
    for agent in roots_and_unchanged_children:
        regrouped.append(agent)
        if agent.raw_suffix is None:
            continue
        regrouped.extend(children_by_parent.pop(agent.raw_suffix, []))

    for remaining_children in children_by_parent.values():
        regrouped.extend(remaining_children)
    return regrouped


def _normalize_relationships_after_merge(agents: list[Agent]) -> list[Agent]:
    """Rebuild child-derived fields after the Tier-1 patch merge."""
    from ...models._agent_ordering import sort_and_reorder
    from ...models._agent_status_overrides import apply_status_overrides

    top_level_and_followups: list[Agent] = []
    workflow_steps: list[Agent] = []
    for agent in agents:
        if agent.parent_workflow:
            workflow_steps.append(agent)
        else:
            top_level_and_followups.append(agent)

    apply_status_overrides(top_level_and_followups, workflow_steps)
    return sort_and_reorder(top_level_and_followups, workflow_steps)


def merge_incomplete_load_after_complete_history(
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyData:
    """Treat post-reconcile Tier 1 loads as patches over full history."""
    load_state = snapshot.load_state
    if (
        load_state is None
        or load_state.complete_history
        or not snapshot.agents_seen_complete_history
    ):
        return prep

    cached_agents = list(snapshot.cached_agents_with_children)
    if not cached_agents:
        return prep

    from ...models._dedup import dedup_by_pid, dedup_running_vs_workflow
    from ...models.agent import AgentType

    incoming_by_identity = {agent.identity: agent for agent in prep.filtered_agents}
    dismissed = set(snapshot.dismissed_agents)
    dismissed_suffixes = {
        raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None
    }
    dismissed_cl_suffixes = {
        (cl_name, raw_suffix)
        for _, cl_name, raw_suffix in dismissed
        if raw_suffix is not None
    }

    def is_dismissed(agent: Agent) -> bool:
        if agent.identity in dismissed:
            return True
        if agent.raw_suffix is None:
            return False
        if agent.status == "RUNNING":
            return (agent.cl_name, agent.raw_suffix) in dismissed_cl_suffixes or (
                agent.cl_name == "unknown" and agent.raw_suffix in dismissed_suffixes
            )
        return agent.raw_suffix in dismissed_suffixes

    merged: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    cached_identities = {agent.identity for agent in cached_agents}
    cached_parent_by_suffix = {
        agent.raw_suffix: agent
        for agent in cached_agents
        if agent.raw_suffix is not None and not agent.is_workflow_child
    }
    cached_parent_suffixes = set(cached_parent_by_suffix)
    incoming_parent_suffixes = {
        agent.raw_suffix
        for agent in prep.filtered_agents
        if agent.raw_suffix is not None and not agent.is_workflow_child
    }
    known_parent_suffixes = cached_parent_suffixes | incoming_parent_suffixes
    new_roots: list[Agent] = []
    new_children_by_parent: dict[str, list[Agent]] = {}

    def can_canonical_dedup_running_shadow(agent: Agent) -> bool:
        """Whether loader-level RUNNING-WORKFLOW dedup can handle this row."""
        cached_parent = (
            cached_parent_by_suffix.get(agent.raw_suffix)
            if agent.raw_suffix is not None
            else None
        )
        return (
            agent.agent_type == AgentType.RUNNING
            and cached_parent is not None
            and cached_parent.agent_type == AgentType.WORKFLOW
            and agent.workflow is not None
            and (
                agent.workflow.startswith("ace(run)")
                or agent.workflow == "ace-run"
                or agent.workflow == "run"
            )
        )

    # Newly discovered Tier 1 rows are usually the newest rows. Keep their
    # relative Tier 1 order while preserving cached parent/child groups.
    for agent in prep.filtered_agents:
        if agent.identity in cached_identities or is_dismissed(agent):
            continue
        if agent.parent_timestamp and agent.parent_timestamp in known_parent_suffixes:
            new_children_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
            continue
        if (
            agent.raw_suffix is not None
            and not agent.is_workflow_child
            and agent.raw_suffix in cached_parent_suffixes
            and not can_canonical_dedup_running_shadow(agent)
        ):
            continue
        new_roots.append(agent)

    for agent in new_roots:
        if agent.identity in seen:
            continue
        merged.append(agent)
        seen.add(agent.identity)
        if agent.raw_suffix:
            for child in new_children_by_parent.pop(agent.raw_suffix, []):
                if child.identity in seen:
                    continue
                merged.append(child)
                seen.add(child.identity)

    for cached in cached_agents:
        replacement = incoming_by_identity.get(cached.identity, cached)
        if replacement.identity in seen or is_dismissed(replacement):
            continue
        merged.append(replacement)
        seen.add(replacement.identity)
        if replacement.raw_suffix:
            for child in new_children_by_parent.pop(replacement.raw_suffix, []):
                if child.identity in seen:
                    continue
                merged.append(child)
                seen.add(child.identity)

    before_dedup = list(merged)
    merged = dedup_running_vs_workflow(merged)
    merged = dedup_by_pid(merged)
    merged = _reattach_children_after_parent_dedup(before_dedup, merged)
    merged = _normalize_relationships_after_merge(merged)

    always_visible = [agent for agent in merged if is_always_visible(agent)]
    hideable = [agent for agent in merged if not is_always_visible(agent)]
    if always_visible and snapshot.hide_non_run_agents and hideable:
        filtered_agents = always_visible
        hidden_count = len(hideable)
    else:
        filtered_agents = merged
        hidden_count = 0

    prep.filtered_agents = filtered_agents
    prep.hidden_count = hidden_count
    prep.has_always_visible = bool(always_visible)
    prep.hideable_agents = hideable
    return prep

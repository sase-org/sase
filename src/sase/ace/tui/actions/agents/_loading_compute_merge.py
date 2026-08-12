"""Tier-1 patch merge logic for :func:`prepare_loaded_agents_apply_boundary`.

Splits off the post-history merge that folds an incoming Tier 1 partial
load on top of the cached complete-history view. Lives in its own
module so the entry point in :mod:`._loading_compute` stays small.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.agent_clan_context import clan_context_key
from sase.core.agent_scan_wire import AgentClanContextWire

from ._loading_compute_types import PreparedApplyData, PreparedApplySnapshot
from ._loading_helpers import is_always_visible

if TYPE_CHECKING:
    from ...models import Agent


_Tier1MergeKey = tuple[object, ...]


def _merge_clan_context(
    previous: AgentClanContextWire | None,
    current: AgentClanContextWire | None,
) -> AgentClanContextWire | None:
    """Keep resolved Tier-2 attributes across a partial Tier-1 replacement."""
    if previous is None:
        return current
    if current is None:
        return previous
    keep_tribe = not current.clan_tribe and bool(previous.clan_tribe)
    keep_summary = not current.clan_summary and bool(previous.clan_summary)
    if not keep_tribe and not keep_summary:
        return current
    return replace(
        current,
        clan_tribe=previous.clan_tribe if keep_tribe else current.clan_tribe,
        clan_tribe_source_launch_timestamp=(
            previous.clan_tribe_source_launch_timestamp
            if keep_tribe
            else current.clan_tribe_source_launch_timestamp
        ),
        clan_tribe_source_identity=(
            previous.clan_tribe_source_identity
            if keep_tribe
            else current.clan_tribe_source_identity
        ),
        clan_summary=(previous.clan_summary if keep_summary else current.clan_summary),
        clan_summary_source_launch_timestamp=(
            previous.clan_summary_source_launch_timestamp
            if keep_summary
            else current.clan_summary_source_launch_timestamp
        ),
        clan_summary_source_identity=(
            previous.clan_summary_source_identity
            if keep_summary
            else current.clan_summary_source_identity
        ),
    )


def _identity_merge_key(agent: Agent) -> _Tier1MergeKey:
    return ("identity", agent.agent_type, agent.cl_name, agent.raw_suffix)


def _tier1_merge_key(agent: Agent) -> _Tier1MergeKey:
    """Stable replacement key for patching Tier 1 rows over cached history."""
    if agent.raw_suffix is None:
        return _identity_merge_key(agent)
    if agent.parent_workflow is not None:
        return (
            "artifact-step",
            agent.agent_type,
            agent.raw_suffix,
            agent.parent_timestamp,
            agent.parent_workflow,
            agent.parent_step_index,
            agent.step_index,
            agent.step_type,
            agent.step_name,
        )
    if agent.parent_timestamp is not None:
        return (
            "artifact-followup",
            agent.agent_type,
            agent.raw_suffix,
            agent.parent_timestamp,
        )
    from ...models.agent import AgentType

    if agent.agent_type != AgentType.WORKFLOW:
        return _identity_merge_key(agent)
    return ("artifact-root", agent.agent_type, agent.raw_suffix)


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

    # See ``normalize_loaded_agents`` in ``_agent_loader_normalization.py``:
    # persisted diff-badge classification is deferred to a background pass, so
    # this merge path must not resurrect it either.
    apply_status_overrides(
        top_level_and_followups, workflow_steps, classify_diff_badges=False
    )
    return sort_and_reorder(top_level_and_followups, workflow_steps)


def merge_incomplete_load_after_complete_history(
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyData:
    """Treat post-reconcile Tier 1 loads as patches over full history."""
    load_state = snapshot.load_state
    is_artifact_delta = (
        load_state is not None and load_state.artifact_source == "artifact_delta"
    )
    if (
        load_state is None
        or load_state.complete_history
        or (not snapshot.agents_seen_complete_history and not is_artifact_delta)
    ):
        return prep

    cached_agents = list(snapshot.cached_agents_with_children)
    if not cached_agents:
        return prep

    cached_context_by_clan: dict[tuple[str, str | None], AgentClanContextWire] = {}
    for cached in cached_agents:
        key = clan_context_key(
            cached.agent_clan,
            cached.agent_clan_generation,
        )
        if key is None or cached.clan_context is None:
            continue
        merged_context = _merge_clan_context(
            cached_context_by_clan.get(key),
            cached.clan_context,
        )
        if merged_context is not None:
            cached_context_by_clan[key] = merged_context
    for incoming in prep.filtered_agents:
        key = clan_context_key(
            incoming.agent_clan,
            incoming.agent_clan_generation,
        )
        if key is None:
            continue
        incoming.clan_context = _merge_clan_context(
            cached_context_by_clan.get(key),
            incoming.clan_context,
        )

    from ...models._dedup import dedup_by_pid, dedup_running_vs_workflow
    from ...models.agent import AgentType

    incoming_by_key = {_tier1_merge_key(agent): agent for agent in prep.filtered_agents}
    dismissed = set(snapshot.dismissed_agents)
    dismissed_suffixes = {
        raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None
    }
    dismissed_cl_suffixes = {
        (cl_name, raw_suffix)
        for _, cl_name, raw_suffix in dismissed
        if raw_suffix is not None
    }
    deleted_artifact_dirs = set(
        getattr(load_state, "deleted_artifact_dirs", frozenset())
    )
    deleted_suffixes = {
        Path(path).name
        for path in deleted_artifact_dirs
        if Path(path).name.isdigit() and len(Path(path).name) == 14
    }

    def is_dismissed(agent: Agent) -> bool:
        if agent.runner_is_live:
            return False
        if agent.identity in dismissed:
            return True
        if agent.raw_suffix is None:
            return False
        if agent.status == "RUNNING":
            return (agent.cl_name, agent.raw_suffix) in dismissed_cl_suffixes or (
                agent.cl_name == "unknown" and agent.raw_suffix in dismissed_suffixes
            )
        return agent.raw_suffix in dismissed_suffixes

    def is_deleted_artifact_delta(agent: Agent) -> bool:
        if not deleted_artifact_dirs:
            return False
        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if artifacts_dir is not None:
            key = str(Path(artifacts_dir).expanduser())
            if key in deleted_artifact_dirs:
                return True
        if agent.raw_suffix is not None and agent.raw_suffix in deleted_suffixes:
            return True
        return (
            agent.parent_timestamp is not None
            and agent.parent_timestamp in deleted_suffixes
        )

    merged: list[Agent] = []
    seen: set[_Tier1MergeKey] = set()
    cached_keys = {_tier1_merge_key(agent) for agent in cached_agents}
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
        agent_key = _tier1_merge_key(agent)
        if agent_key in cached_keys or is_dismissed(agent):
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
        agent_key = _tier1_merge_key(agent)
        if agent_key in seen:
            continue
        merged.append(agent)
        seen.add(agent_key)
        if agent.raw_suffix:
            for child in new_children_by_parent.pop(agent.raw_suffix, []):
                child_key = _tier1_merge_key(child)
                if child_key in seen:
                    continue
                merged.append(child)
                seen.add(child_key)

    for cached in cached_agents:
        replacement = incoming_by_key.get(_tier1_merge_key(cached), cached)
        replacement_key = _tier1_merge_key(replacement)
        if (
            replacement_key in seen
            or is_dismissed(replacement)
            or is_deleted_artifact_delta(replacement)
        ):
            continue
        merged.append(replacement)
        seen.add(replacement_key)
        if replacement.raw_suffix:
            for child in new_children_by_parent.pop(replacement.raw_suffix, []):
                child_key = _tier1_merge_key(child)
                if child_key in seen:
                    continue
                merged.append(child)
                seen.add(child_key)

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

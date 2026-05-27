"""Saved-group resolution helpers for agent revival."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.core.agent_group_archive_wire import (
        SavedAgentGroupRefWire,
        SavedAgentGroupWire,
    )

    from ...models import Agent


def utc_wire_timestamp(value: datetime) -> str:
    """Return a UTC ISO timestamp using the archive wire's ``Z`` convention."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def ref_label(ref: SavedAgentGroupRefWire) -> str:
    name = ref.display_name or ref.agent_name or ref.cl_name or "agent"
    return f"{name} ({ref.raw_suffix or 'no suffix'})"


def pop_first_matching_agent(
    agents: list[Agent],
    predicate: Callable[[Agent], bool],
) -> Agent | None:
    for idx, agent in enumerate(agents):
        if predicate(agent):
            return agents.pop(idx)
    return None


def pop_agent_for_group_ref(
    agents: list[Agent],
    ref: SavedAgentGroupRefWire,
) -> Agent | None:
    """Pop the best loaded dismissed-bundle agent for one saved group ref."""
    if ref.bundle_path:
        exact_path = pop_first_matching_agent(
            agents,
            lambda agent: (
                getattr(agent, "_dismissed_bundle_path", None) == ref.bundle_path
            ),
        )
        if exact_path is not None:
            return exact_path

    if not ref.raw_suffix:
        return None

    def _same_suffix(agent: Agent) -> bool:
        return agent.raw_suffix == ref.raw_suffix

    strict = pop_first_matching_agent(
        agents,
        lambda agent: (
            _same_suffix(agent)
            and agent.agent_type.value == ref.agent_type
            and agent.is_workflow_child == ref.is_workflow_child
            and agent.cl_name == ref.cl_name
            and (
                not ref.parent_timestamp
                or agent.parent_timestamp == ref.parent_timestamp
            )
        ),
    )
    if strict is not None:
        return strict

    child_aware = pop_first_matching_agent(
        agents,
        lambda agent: (
            _same_suffix(agent)
            and agent.is_workflow_child == ref.is_workflow_child
            and (
                not ref.parent_timestamp
                or agent.parent_timestamp == ref.parent_timestamp
            )
        ),
    )
    if child_aware is not None:
        return child_aware

    same_suffix = [agent for agent in agents if _same_suffix(agent)]
    if len(same_suffix) == 1:
        return pop_first_matching_agent(agents, _same_suffix)
    return None


def resolve_saved_group_agents(
    group: SavedAgentGroupWire,
    *,
    bundle_loader: Callable[[set[str]], list[Agent]],
) -> tuple[list[Agent], list[Agent], list[SavedAgentGroupRefWire]]:
    """Load dismissed bundles for a saved group and match them to refs."""
    suffixes = {
        ref.raw_suffix for ref in group.agent_refs if ref.raw_suffix is not None
    }
    if not suffixes:
        return [], [], list(group.agent_refs)

    loaded_agents = bundle_loader(suffixes)
    for agent in loaded_agents:
        agent._loaded_from_dismissed_bundle = True

    remaining = list(loaded_agents)
    resolved: list[Agent] = []
    missing: list[SavedAgentGroupRefWire] = []
    for ref in group.agent_refs:
        matched_agent = pop_agent_for_group_ref(remaining, ref)
        if matched_agent is None:
            missing.append(ref)
            continue
        resolved.append(matched_agent)
    return resolved, loaded_agents, missing

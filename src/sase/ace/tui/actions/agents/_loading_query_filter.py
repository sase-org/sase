"""Shared structured-query filtering for Agents-tab projections."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent_content_search import AgentContentSearchIndex


def filter_agents_by_query(
    agents: list[Agent],
    parsed_ast: QueryExpr,
    content_index: AgentContentSearchIndex | None,
) -> list[Agent]:
    """Filter *agents* by *parsed_ast*, preserving visible child rows.

    Projection contract:
    ``_agents_with_children`` is the unfiltered tree payload and ``_agents`` is
    the current fold/search/group-visible projection. Workflow children remain
    attached through the same parent key used by folding and rendering:
    parent ``raw_suffix`` <-> child ``parent_timestamp``. The legacy name
    fallback keeps older synthetic rows without timestamps working in tests.
    """
    from ....agent_query import evaluate_agent_query

    now = datetime.now()

    def _matches(agent: Agent) -> bool:
        return evaluate_agent_query(
            parsed_ast, agent, now=now, content_cache=content_index
        )

    matching_parent_keys: set[str] = set()
    matching_parent_names: set[str] = set()
    for agent in agents:
        if agent.is_workflow_child or not _matches(agent):
            continue
        if agent.raw_suffix:
            matching_parent_keys.add(agent.raw_suffix)
        matching_parent_names.add(agent.agent_name or agent.cl_name)

    return [
        agent
        for agent in agents
        if (
            _matches(agent)
            or (
                agent.is_workflow_child
                and agent.parent_timestamp is not None
                and agent.parent_timestamp in matching_parent_keys
            )
            or (
                agent.is_workflow_child
                and agent.parent_timestamp is None
                and (agent.agent_name or agent.cl_name) in matching_parent_names
            )
        )
    ]

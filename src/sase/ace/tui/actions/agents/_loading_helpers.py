"""Helper functions and constants for agent loading and filtering."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Statuses that indicate an agent is dismissable (shows "x dismiss" in footer)
DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
    "PLAN COMMITTED",
    "PLAN DONE",
}


def is_always_visible(agent: Agent) -> bool:
    """Check if agent should always be visible (dismissable or running).

    Args:
        agent: The agent to check.

    Returns:
        True if agent should always be visible, False if it's hideable.
    """
    # Workflow children: visibility managed by fold state, not hide toggle
    if agent.is_workflow_child:
        return True

    # Agents marked hidden (via %hide directive, axe-spawned detection, etc.)
    # are hideable (hidden by default, shown with '.' toggle)
    if agent.hidden:
        return False

    return True


def is_axe_spawned_agent(agent: Agent) -> bool:
    """Check if agent was spawned by sase axe (not user-initiated).

    Agents spawned by axe should not trigger notifications since they're
    automated background tasks.

    Args:
        agent: The agent to check.

    Returns:
        True if agent was spawned by axe, False if user-initiated.
    """
    if agent.workflow:
        # Normalize hyphens to underscores (canonical form uses underscores,
        # e.g. xprompt workflow_label "fix_hook")
        workflow = agent.workflow.replace("-", "_")
        # axe-spawned workflows start with axe(...)
        if workflow.startswith(("axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor(")):
            return True
        # Plain workflow names for axe-spawned types (from workflow_state.json or ChangeSpec)
        if workflow in ("fix_hook", "crs", "mentor", "summarize_hook"):
            return True

    return False


def apply_custom_order(
    agents: list[Agent], order: list[tuple[AgentType, str, str | None]]
) -> list[Agent]:
    """Reorder top-level agents according to the user's custom order.

    Agents whose identity appears in *order* are placed at the positions
    specified by the order list.  New agents (not in the order) keep their
    default time-sorted position.  Workflow children stay grouped after
    their parent.
    """
    # Build identity -> desired position lookup
    order_map: dict[tuple[AgentType, str, str | None], int] = {
        identity: pos for pos, identity in enumerate(order)
    }

    # Separate top-level agents from workflow children
    top_level: list[Agent] = []
    children_by_parent: dict[str, list[Agent]] = {}
    for agent in agents:
        if agent.is_workflow_child:
            parent_ts = agent.parent_timestamp or ""
            children_by_parent.setdefault(parent_ts, []).append(agent)
        else:
            top_level.append(agent)

    # Sort top-level: agents in custom order get their specified position,
    # agents not in the order get a high position (preserving relative order)
    max_pos = len(order)
    top_level.sort(
        key=lambda a: (order_map.get(a.identity, max_pos + agents.index(a)),)
    )

    # Reassemble with children after their parents
    result: list[Agent] = []
    for agent in top_level:
        result.append(agent)
        if agent.raw_suffix and agent.raw_suffix in children_by_parent:
            result.extend(children_by_parent[agent.raw_suffix])
    # Append any orphaned children (parent not in list)
    seen_parents = {a.raw_suffix for a in top_level if a.raw_suffix}
    for parent_ts, children in children_by_parent.items():
        if parent_ts not in seen_parents:
            result.extend(children)

    return result


def load_agents_from_disk(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from disk (thread-safe, no app state mutation).

    Args:
        dismissed_agents: Snapshot of dismissed agent identities.

    Returns:
        Tuple of (all_agents, dismissed_from_loader).
    """
    from ...models import load_all_agents

    all_agents = load_all_agents()

    # Populate retry fields from retry_state.json for running agents and
    # prior-attempt history (from attempts/<N>/) for all agents.
    from sase.ace.tui.models.agent import load_attempt_history
    from sase.llm_provider.retry_config import RetryState

    for agent in all_agents:
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir:
            agent.attempt_history = load_attempt_history(artifacts_dir)

        if agent.status != "RUNNING":
            continue
        if not artifacts_dir:
            continue
        retry_state = RetryState.read_from(artifacts_dir)
        if retry_state is None:
            continue
        agent.retry_count = retry_state.retry_count
        agent.max_retries = retry_state.max_retries
        agent.retry_next_at_epoch = retry_state.next_retry_at_epoch
        agent.retry_wait_seconds = retry_state.wait_seconds
        agent.using_fallback = retry_state.using_fallback
        agent.fallback_model = retry_state.fallback_model
        agent.retry_status = retry_state.status
        if retry_state.status == "retrying":
            agent.status = "RETRYING"

    # Build secondary index for robust dismissed matching
    dismissed_suffixes: set[str] = {
        raw_suffix for _, _, raw_suffix in dismissed_agents if raw_suffix is not None
    }

    # Capture dismissed agents found by the loader (for revive + self-healing).
    # Exclude RUNNING agents: a done.json auto-dismiss can share the same
    # identity/raw_suffix as a still-active RUNNING field agent; treating the
    # running agent as dismissed would delete its artifacts and hide it.
    dismissed_from_loader = [
        a
        for a in all_agents
        if a.status != "RUNNING"
        and (
            a.identity in dismissed_agents
            or (a.raw_suffix is not None and a.raw_suffix in dismissed_suffixes)
        )
    ]

    # Supplement with bundles: load saved bundles for agents whose identity
    # is in dismissed_agents but not already found by the loader.
    from ....dismissed_agents import load_dismissed_bundles

    loader_identities = {a.identity for a in dismissed_from_loader}
    loader_suffixes = {
        a.raw_suffix for a in dismissed_from_loader if a.raw_suffix is not None
    }
    needed_suffixes = dismissed_suffixes - loader_suffixes
    for bundled_agent in load_dismissed_bundles(needed_suffixes):
        if bundled_agent.identity not in loader_identities:
            dismissed_from_loader.append(bundled_agent)

    return all_agents, dismissed_from_loader

"""Helper functions and constants for agent loading and filtering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...models import Agent
    from ...models.agent import AgentType  # noqa: F401
    from ...models.agent_loader import AgentLoadState

from ...util.trace import tui_trace

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Statuses that indicate an agent is dismissable (shows "x dismiss" in footer)
DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
    "PLAN COMMITTED",
    "PLAN DONE",
    "PLAN REJECTED",
    "EPIC CREATED",
}


@dataclass(frozen=True)
class _AgentDiskLoadResult:
    """Disk-loaded agents plus the artifact-history completeness state."""

    all_agents: list[Agent]
    dismissed_from_loader: list[Agent]
    load_state: AgentLoadState


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


def load_agents_from_disk(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from disk (thread-safe, no app state mutation).

    Args:
        dismissed_agents: Snapshot of dismissed agent identities.
        changespec_snapshot: Optional pre-fetched ChangeSpec list. When
            supplied, the loader skips its own ``find_all_changespecs()``
            call and reuses this snapshot for bug/CL lookups.

    Returns:
        Tuple of (all_agents, dismissed_from_loader).
    """
    with tui_trace("agents.load_from_disk"):
        result = _load_agents_from_disk_impl(
            dismissed_agents, changespec_snapshot=changespec_snapshot
        )
    return result.all_agents, result.dismissed_from_loader


def load_agents_from_disk_with_state(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    full_history: bool = False,
) -> _AgentDiskLoadResult:
    """Load agents from disk and include the tiered load state."""

    with tui_trace("agents.load_from_disk"):
        return _load_agents_from_disk_impl(
            dismissed_agents,
            changespec_snapshot=changespec_snapshot,
            full_history=full_history,
        )


def _load_agents_from_disk_impl(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    full_history: bool = False,
) -> _AgentDiskLoadResult:
    from ...models.agent_loader import load_tiered_agents

    all_agents, load_state = load_tiered_agents(
        changespec_snapshot=changespec_snapshot,
        full_history=full_history,
    )

    # Populate retry fields from retry_state.json for running agents and
    # prior-attempt history (from attempts/<N>/) for all agents.
    from sase.ace.agent_tags import load_agent_tags

    from ._snapshot_cache import get_global_snapshot_cache

    snapshot_cache = get_global_snapshot_cache()
    tags_by_identity = load_agent_tags()

    for agent in all_agents:
        if agent.identity in tags_by_identity:
            agent.tag = tags_by_identity[agent.identity]
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir:
            agent.attempt_history = snapshot_cache.attempt_history_for(artifacts_dir)

        if agent.status != "RUNNING":
            continue
        if not artifacts_dir:
            continue
        retry_state = snapshot_cache.retry_state_for(artifacts_dir)
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

    return _AgentDiskLoadResult(
        all_agents=all_agents,
        dismissed_from_loader=dismissed_from_loader,
        load_state=load_state,
    )

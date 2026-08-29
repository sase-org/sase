"""Deduplication, status, ordering, and liveness for loaded agents."""

from collections.abc import Callable

from sase.agent.status_buckets import agent_status_bucket
from sase.core.agent_clan_context import clan_context_by_key, clan_context_for
from sase.core.agent_scan_wire import AgentArtifactScanWire

from ._agent_ordering import sort_and_reorder
from ._agent_status_apply import apply_status_overrides
from ._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from .agent import Agent
from .agent_family_members import row_is_family_shell


_LIVE_PLAN_AGENT_BUCKETS = frozenset(
    {"Stopped", "Starting", "Running", "Queued", "Waiting"}
)


def apply_snapshot_clan_context(
    agents: list[Agent],
    snapshot: AgentArtifactScanWire,
) -> None:
    """Attach snapshot-only clan context to matching loaded member rows."""
    contexts = clan_context_by_key(snapshot.clan_context)
    if not contexts:
        return
    for agent in agents:
        context = clan_context_for(
            contexts,
            agent_clan=agent.agent_clan,
            agent_clan_generation=agent.agent_clan_generation,
        )
        if context is not None:
            agent.clan_context = context


def _filter_dead_pids(
    agents: list[Agent],
    *,
    is_process_running: Callable[[int], bool],
) -> list[Agent]:
    """Drop agent rows whose recorded PID is dead.

    OS process liveness gates *agent* rows. A family shell's own
    ``gate_state`` / ``monitor_state`` gates shell rows — a pending gate
    shell has no process at all, and may inherit its creator's dead pid.
    """

    verified_agents: list[Agent] = []
    completed_statuses = ("DONE", "FAILED")
    for agent in agents:
        if row_is_family_shell(agent):
            verified_agents.append(agent)
        elif agent.status in completed_statuses:
            verified_agents.append(agent)
        elif agent.pid is not None:
            if is_process_running(agent.pid):
                verified_agents.append(agent)
        else:
            verified_agents.append(agent)
    return verified_agents


def _deduplicate(agents: list[Agent]) -> list[Agent]:
    agents = dedup_axe_spawned_agents(agents)
    agents = remove_vcs_workspace_claims(agents)
    agents = dedup_workflow_entries(agents)
    agents = dedup_running_vs_workflow(agents)
    return dedup_by_pid(agents)


def normalize_loaded_agents(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
    *,
    is_process_running: Callable[[int], bool],
    keep_orphaned_followups: bool = False,
) -> list[Agent]:
    """Normalize and order agents from the full or delta loading paths."""

    agents = _filter_dead_pids(agents, is_process_running=is_process_running)
    agents = _deduplicate(agents)
    # Persisted diff-badge classification reads every referenced diff file and
    # dominates startup (~0.4 s over 213 rows). It is display enrichment that
    # nothing downstream depends on, so it is deferred to a background pass
    # after the list has painted (see ``AgentDiffBadgeMixin``).
    apply_status_overrides(agents, workflow_agent_steps, classify_diff_badges=False)
    return sort_and_reorder(
        agents,
        workflow_agent_steps,
        keep_orphaned_followups=keep_orphaned_followups,
    )


def mark_live_artifact_delta_runners(
    agents: list[Agent],
    *,
    is_process_running: Callable[[int], bool],
) -> None:
    """Attach bounded PID liveness proof to exact-delta rows."""

    liveness_by_pid: dict[int, bool] = {}
    for agent in agents:
        if agent.runner_is_live or agent.pid is None:
            continue
        live = liveness_by_pid.get(agent.pid)
        if live is None:
            live = is_process_running(agent.pid)
            liveness_by_pid[agent.pid] = live
        if live:
            agent.runner_is_live = True


def normalize_live_plan_agents(
    agents: list[Agent],
    *,
    is_process_running: Callable[[int], bool],
) -> list[Agent]:
    """Normalize the visibility-affecting pieces used for plan-list matching."""

    agents = _filter_dead_pids(agents, is_process_running=is_process_running)
    agents = _deduplicate(agents)
    apply_status_overrides(agents, classify_diff_badges=False)
    return [agent for agent in agents if _agent_is_live_plan_candidate(agent)]


def _agent_is_live_plan_candidate(agent: Agent) -> bool:
    bucket = agent_status_bucket(agent)
    return bucket in _LIVE_PLAN_AGENT_BUCKETS

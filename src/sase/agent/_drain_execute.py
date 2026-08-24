"""Apply a planned provider drain.

Execution runs each move sequentially through
``sase.agent.restart.execute_agent_restart()``, which never raises for one
bad row — a ``kill_failed`` / ``wipe_failed`` / ``partial`` outcome is
collected and the drain continues. Sequential is deliberate: launch
admission and runner slots already throttle relaunches, and a parallel
storm would fight them.
"""

from __future__ import annotations

from sase.agent._drain_types import ProviderDrainOutcome, ProviderDrainPlan
from sase.agent.restart import AgentRestartOutcome, ProgressFn


def execute_provider_drain(
    plan: ProviderDrainPlan,
    *,
    progress: ProgressFn | None = None,
) -> ProviderDrainOutcome:
    """Restart every move in *plan*, one at a time, and collect the results."""
    from sase.agent.restart import execute_agent_restart

    results: list[AgentRestartOutcome] = [
        execute_agent_restart(move.restart_plan, progress=progress)
        for move in plan.moves
    ]
    return ProviderDrainOutcome(plan=plan, results=tuple(results))

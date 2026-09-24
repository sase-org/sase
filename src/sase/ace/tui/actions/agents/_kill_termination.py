"""Durable-stage process termination for agent kill and dismiss transactions.

The TUI only sends the immediate SIGTERM. The ``sase agent persist-cleanup``
proc runs out of process, so it survives the TUI: it terminates each agent's
whole process set, verifies death, and only then lets the transaction release
workspaces and delete artifacts. An agent that cannot be verified dead keeps
its workspace claim and artifacts, and the transaction reports the survivors.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.agent import user_kill
from sase.agent.user_kill import (
    AgentTerminationResult,
    ensure_user_kill_intent,
    live_verified_agent_pid,
)
from sase.core.agent_cleanup_wire import DISMISSABLE_STATUSES

from ._dismiss_cleanup import agent_wire_identity, wire_identity_key

if TYPE_CHECKING:
    from ...models import Agent

# Success-terminal rows keep a live runner only while it runs host-owned
# finalizers, which exit on their own. Dismissing them must not signal the
# runner. FAILED is excluded on purpose: a FAILED row can be in retry backoff,
# and its runner is still doing work.
SUCCESS_TERMINAL_STATUSES = frozenset(DISMISSABLE_STATUSES) - {"FAILED"}

_CLEANUP_SOURCE = "persist_cleanup"
_MAX_PARALLEL_TERMINATIONS = 8


class AgentSurvivorsError(RuntimeError):
    """Killed agents still have running processes after SIGKILL."""


@dataclass(frozen=True)
class Survivor:
    """An agent whose process set could not be verified dead."""

    agent: Agent
    result: AgentTerminationResult


def _terminate_one(agent: Agent) -> AgentTerminationResult:
    pid = agent.pid
    assert pid is not None
    artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
    marker = ensure_user_kill_intent(
        artifacts_dir, pid=pid, source=_CLEANUP_SOURCE, reason=agent.display_name
    )
    try:
        # Resolved through the module so the test-suite guard that confines
        # signalling to the test's own children also covers this call.
        return user_kill.terminate_agent_processes(
            pid, artifacts_dir=artifacts_dir, marker_path=marker
        )
    except Exception as exc:
        return AgentTerminationResult(False, "error", pid, pid, error=str(exc))


def terminate_agents(agents: Iterable[Agent]) -> list[Survivor]:
    """Terminate every agent's process set in parallel; return the survivors.

    Agents sharing a pid (a workflow and its step rows) are terminated once.
    """
    unique: dict[int, Agent] = {}
    for agent in agents:
        if agent.pid is not None:
            unique.setdefault(agent.pid, agent)
    if not unique:
        return []
    ordered = list(unique.values())
    with ThreadPoolExecutor(
        max_workers=min(_MAX_PARALLEL_TERMINATIONS, len(ordered))
    ) as pool:
        results = list(pool.map(_terminate_one, ordered))
    return [
        Survivor(agent, result)
        for agent, result in zip(ordered, results, strict=True)
        if not result.success
    ]


def live_dismissed_agents(
    agents: Iterable[Agent],
    *,
    handled_pids: Collection[int] = (),
) -> list[Agent]:
    """Return dismissed agents whose runner is provably still alive.

    The safety net for rows a planner classified as dismiss-only. Success-
    terminal rows are skipped, and the recorded process identity must be
    verifiable and match, so a recycled pid is never signalled.
    """
    seen = set(handled_pids)
    live: list[Agent] = []
    for agent in agents:
        pid = agent.pid
        if pid is None or pid in seen or agent.status in SUCCESS_TERMINAL_STATUSES:
            continue
        artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
        if not live_verified_agent_pid(pid, artifacts_dir=artifacts_dir):
            continue
        seen.add(pid)
        live.append(agent)
    return live


def survivor_agents(survivors: Sequence[Survivor]) -> list[Agent]:
    return [survivor.agent for survivor in survivors]


def withhold_agent_side_effects(
    plan: Any,
    survivors: Sequence[Agent],
    agents_with_children: Sequence[Agent],
) -> Any:
    """Drop workspace-release and artifact-delete intents for survivors.

    A survivor's own row, its workflow step rows, and its clan members' rows
    are withheld: their processes may still be using the workspace and
    artifacts. Everything else in the plan runs unchanged.
    """
    side_effects = getattr(plan, "side_effects", None)
    if plan is None or side_effects is None or not survivors:
        return plan
    withheld = {agent_wire_identity(agent) for agent in survivors}
    for survivor in survivors:
        if survivor.is_workflow_child or not survivor.raw_suffix:
            continue
        withheld.update(
            agent_wire_identity(step)
            for step in agents_with_children
            if step.is_workflow_child
            and step.parent_timestamp == survivor.raw_suffix
            and step.parent_workflow == survivor.workflow
        )

    def keep(intent: Any) -> bool:
        return wire_identity_key(intent.identity) not in withheld

    return dataclasses.replace(
        plan,
        side_effects=dataclasses.replace(
            side_effects,
            artifact_delete_paths=tuple(
                intent for intent in side_effects.artifact_delete_paths if keep(intent)
            ),
            workspace_release_requests=tuple(
                intent
                for intent in side_effects.workspace_release_requests
                if keep(intent)
            ),
        ),
    )


def survivors_error(survivors: Sequence[Survivor]) -> AgentSurvivorsError:
    """Build the transaction failure naming every survivor pid."""
    pids = sorted(
        {pid for survivor in survivors for pid in survivor.result.survivors}
        | {
            survivor.result.pid
            for survivor in survivors
            if not survivor.result.survivors
        }
    )
    names = ", ".join(sorted({s.agent.display_name for s in survivors}))
    return AgentSurvivorsError(
        f"could not verify death of PID(s) {', '.join(str(pid) for pid in pids)} "
        f"({names}); workspace claims and artifacts were kept"
    )


__all__ = [
    "SUCCESS_TERMINAL_STATUSES",
    "AgentSurvivorsError",
    "Survivor",
    "live_dismissed_agents",
    "survivor_agents",
    "survivors_error",
    "terminate_agents",
    "withhold_agent_side_effects",
]

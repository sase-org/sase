"""UI-free durable cleanup for a rejected plan's planner agent.

When a plan is rejected, the matching planner agent is user-killed and its
Agents-tab row is hidden through the same dismissed-agent persistence and
artifact-index projection the TUI uses. This module performs that work
without any Textual app state so headless callers (``sase plan reject``)
produce identical durable state to a TUI rejection.

The TUI keeps its own latency-sensitive optimistic path (``_do_kill_agent``);
both paths converge on the same durable transaction helper
(``persist_single_kill_transaction``) and the same identity-collection
functions, so the dismissed state after refresh is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sase.notifications.agent_matching import agent_matches_notification_identity

from ._kill_cleanup_planning import plan_single_agent_kill_cleanup
from ._kill_identity import (
    agents_related_to_kill,
    classify_kill_kind,
    collect_planned_kill_identities,
)
from ._kill_persistence import AgentIdentity, KillKind
from ._kill_transactions import persist_single_kill_transaction

if TYPE_CHECKING:
    from sase.notifications.models import Notification

    from ...models import Agent


@dataclass(frozen=True)
class PlanRejectionCleanupResult:
    """Outcome of durable agent cleanup for a rejected plan."""

    agent_found: bool
    killed: bool
    dismissed_identities: frozenset[AgentIdentity] = field(default_factory=frozenset)
    error: str | None = None
    warning: str | None = None


def perform_plan_rejection_cleanup(
    notification: Notification, *, source: str = "ace_cli"
) -> PlanRejectionCleanupResult:
    """User-kill and dismiss the planner agent behind a rejected plan.

    Mirrors the TUI reject-without-feedback path: locate the matching live
    agent, signal it through :func:`request_user_kill` (writing the same
    ``.sase_user_kill_pending`` marker), then run the shared durable kill
    transaction so the Agents-tab row is hidden on the next refresh.

    Returns a result describing what happened. When no matching agent is
    found, the result carries a warning (the plan rejection itself still
    succeeds). When the process signal fails hard (e.g. permission denied),
    the row is *not* persisted as dismissed and the result carries an error,
    matching the point at which the TUI bails out before persistence.
    """
    agents = _load_candidate_agents(notification)
    agent = next(
        (a for a in agents if agent_matches_notification_identity(a, notification)),
        None,
    )
    if agent is None:
        return PlanRejectionCleanupResult(
            agent_found=False,
            killed=False,
            warning="no Agents-tab row found to dismiss",
        )

    kind = classify_kill_kind(agent)
    if kind is None:
        return PlanRejectionCleanupResult(
            agent_found=True,
            killed=False,
            error=f"unknown agent type: {agent.agent_type}",
        )

    kill_error = _signal_user_kill(agent, source=source)
    if kill_error is not None:
        return PlanRejectionCleanupResult(
            agent_found=True,
            killed=False,
            error=kill_error,
        )

    identities = _persist_durable_kill(agent, kind, agents)
    return PlanRejectionCleanupResult(
        agent_found=True,
        killed=True,
        dismissed_identities=frozenset(identities),
    )


def _signal_user_kill(agent: Agent, *, source: str) -> str | None:
    """Signal the agent's process group; return an error string on hard failure."""
    if agent.pid is None:
        return None

    from sase.agent.user_kill import request_user_kill

    artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
    result = request_user_kill(
        agent.pid,
        artifacts_dir=artifacts_dir,
        source=source,
        reason=agent.display_name,
    )
    if result.success:
        return None
    return result.error or f"failed to kill PID {agent.pid} ({result.status})"


def _persist_durable_kill(
    agent: Agent, kind: KillKind, agents_snapshot: list[Agent]
) -> set[AgentIdentity]:
    """Run the same durable kill transaction the TUI persists in the background."""
    from ....dismissed_agents import (
        load_dismissed_agents,
        snapshot_dismissed_agents,
    )

    cleanup_plan = plan_single_agent_kill_cleanup(agent, agents_snapshot)
    identities = collect_planned_kill_identities(agent, agents_snapshot, cleanup_plan)

    dismissed = load_dismissed_agents()
    dismissed.update(identities)
    dismissed_snapshot = snapshot_dismissed_agents(dismissed)

    related_agents = agents_related_to_kill(agent, agents_snapshot)
    persist_single_kill_transaction(
        agent,
        kind,
        agents_snapshot,
        dismissed_snapshot,
        cleanup_plan,
        related_agents,
    )
    return identities


def _load_candidate_agents(notification: Notification) -> list[Agent]:
    """Load the live plan-agent rows that could match this notification."""
    from sase.ace.tui.models.agent_loader import (
        load_live_plan_agents,
        load_live_plan_agents_for_timestamps,
    )

    agents: list[Agent] = list(load_live_plan_agents())
    timestamps = [
        timestamp
        for timestamp in (
            notification.action_data.get("agent_timestamp"),
            notification.action_data.get("agent_root_timestamp"),
        )
        if timestamp
    ]
    if timestamps:
        agents.extend(load_live_plan_agents_for_timestamps(timestamps))

    seen: set[AgentIdentity] = set()
    unique: list[Agent] = []
    for agent in agents:
        if agent.identity in seen:
            continue
        seen.add(agent.identity)
        unique.append(agent)
    return unique

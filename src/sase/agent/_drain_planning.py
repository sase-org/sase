"""Plan a provider drain without mutating anything.

Planning is read-only: it resolves the active disable, selects candidate
rows, replans each one through ``sase.agent.restart``'s own read-only
planner, and classifies the resulting rewritten prompt's route through
``sase.agent.launch_guard.plan_launch_units``. A per-agent refusal never
aborts the whole plan — it becomes a skip instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent._drain_selection import select_drain_candidates
from sase.agent._drain_types import (
    DrainRoute,
    ProviderDrainError,
    ProviderDrainMove,
    ProviderDrainPlan,
    ProviderDrainSkip,
)
from sase.agent.running_listing import RunningAgentInfo

if TYPE_CHECKING:
    from sase.agent.launch_guard import LaunchUnit, LaunchUnitCandidate

_DEFAULT_LIMIT = 20


def plan_provider_drain(
    provider: str,
    *,
    model_override: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    now: float | None = None,
) -> ProviderDrainPlan:
    """Build a drain plan for *provider*, or raise :class:`ProviderDrainError`."""
    from sase.agent.running_listing import list_all_agents
    from sase.llm_provider.provider_disable import get_active_provider_disable

    disable = get_active_provider_disable(provider, now)
    if disable is None:
        raise ProviderDrainError(
            reason="not_disabled",
            message=f"'{provider}' has no active disable; nothing to drain.",
            hint="Disable it first in Launch Control's Models panel.",
        )
    if not disable.is_hard:
        raise ProviderDrainError(
            reason="soft_disabled",
            message=(
                f"'{provider}' is only soft-disabled; launches still route to "
                "it, so nothing is stranded."
            ),
            hint="A drain only follows a hard disable.",
        )

    snapshot = list_all_agents()
    candidates, skips = select_drain_candidates(snapshot, provider, disable)

    moves: list[ProviderDrainMove] = []
    for row in candidates:
        outcome = _plan_one(row, provider, model_override=model_override)
        if isinstance(outcome, ProviderDrainSkip):
            skips.append(outcome)
        else:
            moves.append(outcome)

    kept_moves, capped_skips = _apply_limit(moves, limit)
    skips.extend(capped_skips)

    return ProviderDrainPlan(
        provider=provider,
        disable=disable,
        moves=tuple(kept_moves),
        skips=tuple(skips),
        model_override=model_override,
        limit=limit,
    )


def _plan_one(
    row: RunningAgentInfo,
    provider: str,
    *,
    model_override: str | None,
) -> ProviderDrainMove | ProviderDrainSkip:
    from sase.agent.restart import AgentRestartError, plan_agent_restart
    from sase.core.agent_identity_facade import present_agent_name

    assert row.name is not None
    try:
        plan = plan_agent_restart(row.name, model_override=model_override)
    except AgentRestartError as exc:
        return ProviderDrainSkip(
            name=row.name,
            presented_name=present_agent_name(row.name),
            status=row.status,
            reason=exc.reason,
            detail=exc.message,
        )

    route = _classify_route(plan.rewritten_prompt)
    if route.kind == "stranded":
        target = _route_label(route, provider)
        return ProviderDrainSkip(
            name=row.name,
            presented_name=plan.presented_name,
            status=row.status,
            reason="stranded",
            detail=f"pinned to {target}; not reachable from any enabled provider",
        )
    return ProviderDrainMove(
        name=row.name,
        presented_name=plan.presented_name,
        project=plan.project,
        status=row.status,
        route=route,
        restart_plan=plan,
    )


def _classify_route(rewritten_prompt: str) -> DrainRoute:
    from sase.agent.launch_guard import plan_launch_units

    units = plan_launch_units(rewritten_prompt)
    stranded = bool(units) and all(unit.blocked for unit in units)
    candidate = _resolved_candidate(units[0]) if units else None
    return DrainRoute(
        kind="stranded" if stranded else "reroute",
        target_provider=candidate.provider if candidate else None,
        target_model=candidate.model if candidate else None,
    )


def _resolved_candidate(unit: LaunchUnit) -> LaunchUnitCandidate | None:
    if not unit.candidates:
        return None
    for candidate in unit.candidates:
        if candidate.blocked_by is None and not candidate.unavailable:
            return candidate
    return unit.candidates[0]


def _route_label(route: DrainRoute, provider: str) -> str:
    if route.target_provider and route.target_model:
        return f"{route.target_provider}/{route.target_model}"
    return f"{provider}/?"


def _apply_limit(
    moves: list[ProviderDrainMove], limit: int
) -> tuple[list[ProviderDrainMove], list[ProviderDrainSkip]]:
    if limit < 0 or len(moves) <= limit:
        return moves, []
    dropped = moves[limit:]
    capped_skips = [
        ProviderDrainSkip(
            name=move.name,
            presented_name=move.presented_name,
            status=move.status,
            reason="capped",
            detail=f"dropped by --limit {limit}",
        )
        for move in dropped
    ]
    return moves[:limit], capped_skips

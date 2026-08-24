"""Plan and apply a provider drain without touching ACE/TUI/CLI code.

Draining a hard-disabled provider relaunches every agent it stranded and
reports every agent it could not move. Planning is read-only: it selects
candidate rows from a fresh :func:`~sase.agent.running_listing.list_all_agents`
snapshot, replans each one through :mod:`sase.agent.restart`'s own
read-only planner, and classifies the resulting route through
:func:`sase.agent.launch_guard.plan_launch_units`. Execution then applies
the plan by calling :func:`sase.agent.restart.execute_agent_restart` for
each move, sequentially, never raising for one failed move.

This module is the seam callers import; the work lives in
``_drain_selection`` (candidate rows), ``_drain_planning`` (the read-only
plan), ``_drain_execute`` (the mutating half), and ``_drain_types`` (shared
dataclasses).
"""

from __future__ import annotations

from sase.agent import _drain_execute as _execute
from sase.agent import _drain_planning as _planning
from sase.agent import _drain_types as _types

DrainRoute = _types.DrainRoute
ProviderDrainError = _types.ProviderDrainError
ProviderDrainMove = _types.ProviderDrainMove
ProviderDrainOutcome = _types.ProviderDrainOutcome
ProviderDrainPlan = _types.ProviderDrainPlan
ProviderDrainSkip = _types.ProviderDrainSkip

plan_provider_drain = _planning.plan_provider_drain
execute_provider_drain = _execute.execute_provider_drain

__all__ = [
    "DrainRoute",
    "ProviderDrainError",
    "ProviderDrainMove",
    "ProviderDrainOutcome",
    "ProviderDrainPlan",
    "ProviderDrainSkip",
    "execute_provider_drain",
    "plan_provider_drain",
]

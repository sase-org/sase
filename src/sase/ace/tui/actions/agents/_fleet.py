"""Unified remote hydration for the Agents list."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sase.dispatch.federation import (
    FederationConfig,
    FederationConfigError,
    FederationFacade,
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
    build_federation_facade,
    load_federation_config,
)
from sase.dispatch.follow_store import (
    FollowStoreError,
    FollowStoreSnapshot,
    load_follow_snapshot,
    promote_family_follow,
)

from ...models.fleet_agents import FleetRowsProjection
from ._fleet_common import (
    _AGENTS_SUBTABS,
    _FLEET_CATALOG_MAX_PAGES,
    _FLEET_CATALOG_PAGE_LIMIT,
)
from ._fleet_dispatch_launches import AgentFleetDispatchLaunchMixin
from ._fleet_follow import (
    load_reconciled_follow_snapshot,
    reconcile_followed_batch_family_promotions,
)
from ._fleet_header import AgentFleetHeaderMixin
from ._fleet_projection import AgentFleetProjectionMixin
from ._fleet_refresh import AgentFleetRefreshMixin

if TYPE_CHECKING:
    from ...app import AgentsSubTab
    from ...models import Agent

_load_reconciled_follow_snapshot = load_reconciled_follow_snapshot
_reconcile_followed_batch_family_promotions = reconcile_followed_batch_family_promotions


class AgentFleetMixin(
    AgentFleetRefreshMixin,
    AgentFleetHeaderMixin,
    AgentFleetProjectionMixin,
    AgentFleetDispatchLaunchMixin,
):
    """Remote fleet state, projection, and user actions."""

    current_agents_subtab: AgentsSubTab
    current_tab: str
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agents_capacity_with_children: list[Agent]
    _agents_local_with_children: list[Agent]
    _agents_fleet_rows: list[Agent]
    _agents_fleet_focus_rows: list[Agent]
    _agents_dispatch_provisional_rows: dict[str, Agent]
    _dispatch_launch_prompt_to_operation: dict[str, str]
    _agents_fleet_projection: FleetRowsProjection
    _agents_fleet_applied_projection_signature: object | None
    _agents_fleet_async_tasks: set[asyncio.Task[object]]
    _agents_fleet_refresh_generation: int
    _agents_fleet_loading: bool
    _agents_fleet_available: bool
    _agents_fleet_last_error: str | None


__all__ = [
    "AgentFleetMixin",
    "FederationConfig",
    "FederationConfigError",
    "FederationFacade",
    "FederationWorkerResponseError",
    "FederationWorkerUnavailable",
    "FollowStoreError",
    "FollowStoreSnapshot",
    "_AGENTS_SUBTABS",
    "_FLEET_CATALOG_MAX_PAGES",
    "_FLEET_CATALOG_PAGE_LIMIT",
    "_load_reconciled_follow_snapshot",
    "_reconcile_followed_batch_family_promotions",
    "build_federation_facade",
    "load_federation_config",
    "load_follow_snapshot",
    "promote_family_follow",
]

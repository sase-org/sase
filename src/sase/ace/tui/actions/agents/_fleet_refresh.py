"""Fleet refresh, catalog hydration, and projection application."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from sase.dispatch.federation import (
    FederationConfig,
    FederationConfigError,
    FederationFacade,
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
    build_federation_facade,
    load_federation_config,
)
from sase.dispatch.follow_store import FollowStoreError

from ...models.fleet_agents import (
    FleetRowsProjection,
    catalog_next_cursors_by_host,
    merge_catalog_pages,
    project_fleet_agents,
)
from ...util.pump_tasks import spawn_pump_free_task
from ._fleet_common import (
    _FLEET_CATALOG_MAX_PAGES,
    _FLEET_CATALOG_PAGE_LIMIT,
    fleet_public_override,
)
from ._fleet_follow import (
    followed_logical_keys,
    load_reconciled_follow_snapshot,
    reconcile_followed_batch_family_promotions,
)

if TYPE_CHECKING:
    from ...app import AgentsSubTab
    from ...models import Agent

log = logging.getLogger(__name__)


class AgentFleetRefreshMixin:
    """Refresh remote fleet rows and apply their projections."""

    if TYPE_CHECKING:
        current_agents_subtab: AgentsSubTab
        current_tab: str
        _agents_fleet_rows: list[Agent]
        _agents_fleet_focus_rows: list[Agent]
        _agents_fleet_async_tasks: set[asyncio.Task[object]]
        _agents_fleet_refresh_generation: int
        _agents_fleet_loading: bool
        _agents_fleet_available: bool
        _agents_fleet_last_error: str | None
        _agents_fleet_projection: FleetRowsProjection

    def _schedule_agents_fleet_refresh(
        self,
        *,
        source: str,
        force: bool = False,
    ) -> None:
        if self.current_tab != "agents":
            self._update_agents_header()  # type: ignore[attr-defined]
            return
        self._agents_fleet_refresh_generation += 1
        generation = self._agents_fleet_refresh_generation
        if force:
            for task in tuple(getattr(self, "_agents_fleet_async_tasks", ())):
                if not task.done():
                    task.cancel()
        self._agents_fleet_loading = True
        self._update_agents_header()  # type: ignore[attr-defined]
        task = spawn_pump_free_task(
            self,
            self._run_agents_fleet_refresh(generation=generation, source=source),
            name="sase-agents-fleet-refresh",
            registry_attr="_agents_fleet_async_tasks",
        )
        if task is None:
            self._agents_fleet_loading = False
            self._update_agents_header()  # type: ignore[attr-defined]

    async def _run_agents_fleet_refresh(self, *, generation: int, source: str) -> None:
        del source
        deferred_apply = False
        try:
            load_config = fleet_public_override(
                "load_federation_config",
                load_federation_config,
            )
            load_follow_snapshot = fleet_public_override(
                "_load_reconciled_follow_snapshot",
                load_reconciled_follow_snapshot,
            )
            config = await asyncio.to_thread(load_config)
            follow_snapshot = await asyncio.to_thread(load_follow_snapshot)
            summary_response: Mapping[str, Any] | None = None
            followed_response: Mapping[str, Any] | None = None
            catalog_response: Mapping[str, Any] | None = None
            attention_response: Mapping[str, Any] | None = None
            config_diagnostics = config.diagnostics_wire()
            if config.enabled:
                build_facade = fleet_public_override(
                    "build_federation_facade",
                    build_federation_facade,
                )
                facade = build_facade(config)
                timeout = config.worker.request_timeout_seconds
                summary_response = await self._fleet_call(
                    "summary",
                    lambda: facade.summary(
                        cache_only=True,
                        timeout_seconds=timeout,
                    ),
                )
                logical_keys = followed_logical_keys(follow_snapshot)
                if logical_keys:
                    followed_response = await self._fleet_call(
                        "followed_batch",
                        lambda: facade.followed_batch(
                            {
                                "schema_version": 1,
                                "logical_keys": list(logical_keys),
                            },
                            cache_only=False,
                            timeout_seconds=timeout,
                        ),
                    )
                    reconcile_promotions = fleet_public_override(
                        "_reconcile_followed_batch_family_promotions",
                        reconcile_followed_batch_family_promotions,
                    )
                    follow_snapshot = await asyncio.to_thread(
                        reconcile_promotions,
                        follow_snapshot,
                        followed_response,
                    )
                logical_keys = followed_logical_keys(follow_snapshot)
                if logical_keys:
                    attention_response = await self._fleet_call(
                        "attention",
                        lambda: facade.attention(
                            {
                                "schema_version": 1,
                                "logical_keys": list(logical_keys),
                            },
                            cache_only=False,
                            timeout_seconds=timeout,
                        ),
                    )
                catalog_response = await self._fetch_fleet_catalog(
                    facade,
                    timeout_seconds=timeout,
                )
            projection = project_fleet_agents(
                summary_response=summary_response,
                catalog_response=catalog_response,
                followed_response=followed_response,
                attention_response=attention_response,
                follow_snapshot=follow_snapshot,
                local_agent_count=len(getattr(self, "_agents_local_with_children", [])),
            )
            if config_diagnostics:
                projection = FleetRowsProjection(
                    focus_rows=projection.focus_rows,
                    fleet_rows=projection.fleet_rows,
                    diagnostics=(*projection.diagnostics, *config_diagnostics),
                    configured_host_count=projection.configured_host_count
                    or len(config.hosts),
                    partial=projection.partial,
                    counts=dict(projection.counts),
                )
            if self._defer_fleet_projection_apply_if_navigating(
                projection,
                config=config,
                generation=generation,
            ):
                deferred_apply = True
            else:
                self._apply_fleet_projection(
                    projection,
                    config=config,
                    generation=generation,
                )
        except (FederationConfigError, FollowStoreError) as exc:
            log.debug("fleet refresh failed", exc_info=True)
            self._apply_fleet_error(str(exc), generation=generation)
        finally:
            if (
                generation == getattr(self, "_agents_fleet_refresh_generation", 0)
                and not deferred_apply
            ):
                self._agents_fleet_loading = False
                self._update_agents_header()  # type: ignore[attr-defined]

    def _defer_fleet_projection_apply_if_navigating(
        self,
        projection: FleetRowsProjection,
        *,
        config: FederationConfig,
        generation: int,
    ) -> bool:
        nav_gate = getattr(self, "_nav_gate", None)
        if nav_gate is None or not nav_gate.is_navigating():
            return False
        delay = nav_gate.time_until_idle() + 0.05
        self.set_timer(  # type: ignore[attr-defined]
            delay,
            lambda: self._apply_deferred_fleet_projection(
                projection,
                config=config,
                generation=generation,
            ),
        )
        return True

    def _apply_deferred_fleet_projection(
        self,
        projection: FleetRowsProjection,
        *,
        config: FederationConfig,
        generation: int,
    ) -> None:
        if generation != getattr(self, "_agents_fleet_refresh_generation", 0):
            return
        if self._defer_fleet_projection_apply_if_navigating(
            projection,
            config=config,
            generation=generation,
        ):
            return
        self._apply_fleet_projection(
            projection,
            config=config,
            generation=generation,
        )
        if generation == getattr(self, "_agents_fleet_refresh_generation", 0):
            self._agents_fleet_loading = False
            self._update_agents_header()  # type: ignore[attr-defined]

    def _fleet_catalog_request(
        self,
        facade: FederationFacade,
        query: Mapping[str, Any],
        *,
        timeout_seconds: float | None,
    ) -> Callable[[], Awaitable[Mapping[str, Any]]]:
        async def _catalog_page() -> Mapping[str, Any]:
            return await facade.catalog(
                query,
                cache_only=False,
                timeout_seconds=timeout_seconds,
            )

        return _catalog_page

    def _fleet_catalog_hosts_request(
        self,
        facade: FederationFacade,
        queries: tuple[Mapping[str, Any], ...],
        *,
        timeout_seconds: float | None,
    ) -> Callable[[], Awaitable[Mapping[str, Any]]]:
        async def _catalog_page() -> Mapping[str, Any]:
            return await facade.catalog_hosts(
                queries,
                cache_only=False,
                timeout_seconds=timeout_seconds,
            )

        return _catalog_page

    async def _fetch_fleet_catalog(
        self,
        facade: FederationFacade,
        *,
        timeout_seconds: float | None,
    ) -> Mapping[str, Any] | None:
        merged: Mapping[str, Any] | None = None
        base_query: dict[str, Any] = {
            "schema_version": 1,
            "limit": _FLEET_CATALOG_PAGE_LIMIT,
            "include_terminal": True,
        }
        page = await self._fleet_call(
            "catalog",
            self._fleet_catalog_request(
                facade,
                base_query,
                timeout_seconds=timeout_seconds,
            ),
        )
        if page is None:
            return None
        merged = merge_catalog_pages(merged, page)
        cursors = catalog_next_cursors_by_host(page)
        seen: set[tuple[str, str]] = set()
        for _ in range(_FLEET_CATALOG_MAX_PAGES - 1):
            queries = []
            for installation_id, cursor in sorted(cursors.items()):
                marker = (installation_id, cursor)
                if marker in seen:
                    continue
                seen.add(marker)
                query = dict(base_query)
                query["cursor"] = cursor
                queries.append(
                    {
                        "schema_version": 1,
                        "installation_id": installation_id,
                        "query": query,
                    }
                )
            if not queries:
                break
            page = await self._fleet_call(
                "catalog",
                self._fleet_catalog_hosts_request(
                    facade,
                    tuple(queries),
                    timeout_seconds=timeout_seconds,
                ),
            )
            if page is None:
                break
            merged = merge_catalog_pages(merged, page)
            cursors = catalog_next_cursors_by_host(page)
        return merged

    async def _fleet_call(
        self,
        operation: str,
        factory: Callable[[], Awaitable[Mapping[str, Any]]],
    ) -> Mapping[str, Any] | None:
        try:
            return await factory()
        except (FederationWorkerResponseError, FederationWorkerUnavailable) as exc:
            log.debug("fleet %s call failed", operation, exc_info=True)
            return {
                "schema_version": 1,
                "operation": operation,
                "partial": True,
                "hosts": [],
                "diagnostics": [
                    {
                        "code": f"fleet_{operation}_unavailable",
                        "severity": "warning",
                        "message": str(exc),
                    }
                ],
            }

    def _apply_fleet_projection(
        self,
        projection: FleetRowsProjection,
        *,
        config: FederationConfig,
        generation: int,
    ) -> None:
        if generation != getattr(self, "_agents_fleet_refresh_generation", 0):
            return
        self._agents_fleet_projection = projection
        self._agents_fleet_rows = list(projection.fleet_rows)
        self._agents_fleet_focus_rows = list(projection.focus_rows)
        self._agents_fleet_available = bool(
            config.hosts or config.diagnostics or projection.configured_host_count
        )
        self._agents_fleet_last_error = None
        self.current_agents_subtab = "focus"
        self._reproject_agents_from_current_mode(source="fleet_refresh")  # type: ignore[attr-defined]
        self._announce_remote_attention(projection)  # type: ignore[attr-defined]

    def _apply_fleet_error(self, message: str, *, generation: int) -> None:
        if generation != getattr(self, "_agents_fleet_refresh_generation", 0):
            return
        self._agents_fleet_last_error = message
        self._agents_fleet_available = True
        self._agents_fleet_projection = FleetRowsProjection(
            diagnostics=(
                {
                    "code": "fleet_refresh_failed",
                    "severity": "warning",
                    "message": message,
                },
            )
        )
        self._update_agents_header()  # type: ignore[attr-defined]


__all__ = ["AgentFleetRefreshMixin"]

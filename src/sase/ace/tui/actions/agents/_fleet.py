"""Focus/Fleet mode projection and remote hydration for Agents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from textual import on
from textual.widgets import Static

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
    load_follow_snapshot,
    record_follow,
    unfollow,
)

from ...models.fleet_agents import (
    FleetRowsProjection,
    followed_logical_locators,
    project_fleet_agents,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...widgets.panel_tab_strip import PanelTab, PanelTabStrip

if TYPE_CHECKING:
    from ...app import AgentsSubTab
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)

_AGENTS_SUBTABS: tuple[str, str] = ("focus", "fleet")
_FLEET_CATALOG_LIMIT = 250


class AgentFleetMixin:
    """Remote fleet state, projection, and user actions."""

    current_agents_subtab: AgentsSubTab
    current_tab: str
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agents_local_with_children: list[Agent]
    _agents_fleet_rows: list[Agent]
    _agents_fleet_focus_rows: list[Agent]
    _agents_fleet_projection: FleetRowsProjection
    _agents_fleet_async_tasks: set[asyncio.Task[object]]
    _agents_fleet_refresh_generation: int
    _agents_fleet_loading: bool
    _agents_fleet_available: bool
    _agents_fleet_last_error: str | None

    @on(PanelTabStrip.TabClicked)
    def _on_agents_mode_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id not in _AGENTS_SUBTABS:
            return
        event.stop()
        self._set_agents_subtab(event.tab_id)

    def watch_current_agents_subtab(
        self,
        old_mode: AgentsSubTab,
        new_mode: AgentsSubTab,
    ) -> None:
        """Reproject cached Agents rows when Focus/Fleet mode changes."""
        if old_mode == new_mode:
            return
        if new_mode == "fleet" and not self._fleet_mode_available():
            self.current_agents_subtab = "focus"
            self.notify("Fleet view is not configured")  # type: ignore[attr-defined]
            return
        self._reproject_agents_from_current_mode(source="mode_switch")
        self._schedule_agents_fleet_refresh(
            source="mode_switch",
            force=new_mode == "fleet",
        )

    def action_cycle_agents_subtab(self) -> None:
        """Cycle between Focus and Fleet agent modes."""
        self._cycle_agents_subtab(reverse=False)

    def action_cycle_agents_subtab_reverse(self) -> None:
        """Cycle between Focus and Fleet agent modes in reverse."""
        self._cycle_agents_subtab(reverse=True)

    def action_toggle_agent_follow(self) -> None:
        """Follow or unfollow the selected remote fleet row."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        logical_locator = getattr(agent, "fleet_logical_locator", None)
        if agent is None or not isinstance(logical_locator, Mapping):
            self.notify("Select a remote fleet agent to follow")  # type: ignore[attr-defined]
            return
        followed = bool(getattr(agent, "fleet_followed", False))
        task = spawn_pump_free_task(
            self,
            self._toggle_agent_follow_async(
                dict(logical_locator),
                currently_followed=followed,
            ),
            name="sase-agents-fleet-follow",
            registry_attr="_agents_fleet_async_tasks",
        )
        if task is None:
            self.notify("Unable to update fleet follow state", severity="error")  # type: ignore[attr-defined]

    def action_view_agent_in_focus(self) -> None:
        """Switch to Focus mode on the selected followed remote row."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None or not getattr(agent, "fleet_origin_alias", None):
            self.notify("Select a remote fleet agent")  # type: ignore[attr-defined]
            return
        if not getattr(agent, "fleet_followed", False):
            self.notify("Follow the remote agent before viewing it in Focus")  # type: ignore[attr-defined]
            return
        identity = agent.identity
        self.current_agents_subtab = "focus"
        self._select_agent_identity_after_projection(identity)

    def action_connect_agent_machine(self) -> None:
        """Surface the selected remote machine identity."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        alias = getattr(agent, "fleet_origin_alias", None)
        if not alias:
            self.notify("Select a remote fleet agent")  # type: ignore[attr-defined]
            return
        health = getattr(agent, "fleet_connection_health", None) or "unknown health"
        self.notify(f"{alias}: {health}")  # type: ignore[attr-defined]

    def _cycle_agents_subtab(self, *, reverse: bool) -> None:
        if not self._fleet_mode_available():
            self.notify("Fleet view is not configured")  # type: ignore[attr-defined]
            return
        current = self.current_agents_subtab
        if reverse:
            next_mode = "focus" if current == "fleet" else "fleet"
        else:
            next_mode = "fleet" if current == "focus" else "focus"
        self._set_agents_subtab(next_mode)

    def _set_agents_subtab(self, mode: str) -> None:
        self.current_agents_subtab = "fleet" if mode == "fleet" else "focus"

    def _project_agents_for_current_mode_after_load(
        self,
        local_unfiltered: list[Agent],
        local_visible: list[Agent],
    ) -> tuple[list[Agent], list[Agent]]:
        self._agents_local_with_children = list(local_unfiltered)
        self._agents_local_visible = list(local_visible)
        return (
            self._agents_source_for_current_mode(local_unfiltered),
            self._agents_source_for_current_mode(local_visible),
        )

    def _sync_agents_local_source_from_current(self) -> None:
        """Mirror local-only rows after existing in-memory mutations."""
        if self.current_agents_subtab == "fleet":
            return
        self._agents_local_with_children = self._local_agents_from_mixed(
            getattr(self, "_agents_with_children", [])
        )
        self._agents_local_visible = self._local_agents_from_mixed(
            getattr(self, "_agents", [])
        )

    def _agents_source_for_current_mode(self, local_agents: list[Agent]) -> list[Agent]:
        if self.current_agents_subtab == "fleet":
            return list(getattr(self, "_agents_fleet_rows", []))
        return [
            *local_agents,
            *getattr(self, "_agents_fleet_focus_rows", []),
        ]

    @staticmethod
    def _local_agents_from_mixed(agents: list[Agent]) -> list[Agent]:
        return [
            agent for agent in agents if not getattr(agent, "fleet_origin_alias", None)
        ]

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        selected_identity: tuple[AgentType, str, str | None] | None = None,
    ) -> None:
        if selected_identity is None and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        previous_agents = list(getattr(self, "_agents", []))
        local_cache = getattr(self, "_agents_local_with_children", None)
        if local_cache is None:
            local_base = [
                agent
                for agent in getattr(self, "_agents_with_children", [])
                if not getattr(agent, "fleet_origin_alias", None)
            ]
        else:
            local_base = list(local_cache)
        self._agents_with_children = self._agents_source_for_current_mode(local_base)
        self._agents = list(self._agents_with_children)
        self._agents_refresh_active_source = source  # type: ignore[attr-defined]
        try:
            self._finalize_agent_list(  # type: ignore[attr-defined]
                self.current_tab == "agents",
                selected_identity,
                save_unfiltered=False,
                previous_agents=previous_agents,
            )
        finally:
            self._agents_refresh_active_source = "unknown"  # type: ignore[attr-defined]
        self._update_agents_header()

    def _schedule_agents_fleet_refresh(
        self,
        *,
        source: str,
        force: bool = False,
    ) -> None:
        if self.current_tab != "agents":
            self._update_agents_header()
            return
        self._agents_fleet_refresh_generation += 1
        generation = self._agents_fleet_refresh_generation
        if force:
            for task in tuple(getattr(self, "_agents_fleet_async_tasks", ())):
                if not task.done():
                    task.cancel()
        self._agents_fleet_loading = True
        self._update_agents_header()
        task = spawn_pump_free_task(
            self,
            self._run_agents_fleet_refresh(generation=generation, source=source),
            name="sase-agents-fleet-refresh",
            registry_attr="_agents_fleet_async_tasks",
        )
        if task is None:
            self._agents_fleet_loading = False
            self._update_agents_header()

    async def _run_agents_fleet_refresh(self, *, generation: int, source: str) -> None:
        try:
            config = await asyncio.to_thread(load_federation_config)
            follow_snapshot = await asyncio.to_thread(load_follow_snapshot)
            summary_response: Mapping[str, Any] | None = None
            followed_response: Mapping[str, Any] | None = None
            catalog_response: Mapping[str, Any] | None = None
            config_diagnostics = config.diagnostics_wire()
            if config.enabled:
                facade = build_federation_facade(config)
                timeout = config.worker.request_timeout_seconds
                summary_response = await self._fleet_call(
                    "summary",
                    lambda: facade.summary(
                        cache_only=True,
                        timeout_seconds=timeout,
                    ),
                )
                locators = followed_logical_locators(follow_snapshot)
                if locators:
                    followed_response = await self._fleet_call(
                        "followed_batch",
                        lambda: facade.followed_batch(
                            {
                                "schema_version": 1,
                                "logical_locators": list(locators),
                            },
                            cache_only=False,
                            timeout_seconds=timeout,
                        ),
                    )
                if self.current_agents_subtab == "fleet" or source == "manual":
                    catalog_response = await self._fleet_call(
                        "catalog",
                        lambda: facade.catalog(
                            {
                                "schema_version": 1,
                                "limit": _FLEET_CATALOG_LIMIT,
                            },
                            cache_only=False,
                            timeout_seconds=timeout,
                        ),
                    )
            projection = project_fleet_agents(
                summary_response=summary_response,
                catalog_response=catalog_response,
                followed_response=followed_response,
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
            self._apply_fleet_projection(
                projection,
                config=config,
                generation=generation,
            )
        except (FederationConfigError, FollowStoreError) as exc:
            log.debug("fleet refresh failed", exc_info=True)
            self._apply_fleet_error(str(exc), generation=generation)
        finally:
            if generation == getattr(self, "_agents_fleet_refresh_generation", 0):
                self._agents_fleet_loading = False
                self._update_agents_header()

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
        if not self._agents_fleet_available and self.current_agents_subtab == "fleet":
            self.current_agents_subtab = "focus"
        self._reproject_agents_from_current_mode(source="fleet_refresh")

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
        self._update_agents_header()

    async def _toggle_agent_follow_async(
        self,
        logical_locator: dict[str, Any],
        *,
        currently_followed: bool,
    ) -> None:
        try:
            if currently_followed:
                outcome = await asyncio.to_thread(unfollow, logical_locator)
                followed = False
            else:
                outcome = await asyncio.to_thread(record_follow, logical_locator)
                followed = True
        except FollowStoreError as exc:
            self.notify(f"Fleet follow update failed: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        self._set_cached_follow_state(logical_locator, followed)
        changed = "updated" if outcome.changed else "unchanged"
        self.notify(f"Fleet follow {changed}")  # type: ignore[attr-defined]
        self._reproject_agents_from_current_mode(source="fleet_follow")
        self._schedule_agents_fleet_refresh(source="fleet_follow", force=True)

    def _set_cached_follow_state(
        self,
        logical_locator: Mapping[str, Any],
        followed: bool,
    ) -> None:
        locator_id = self._fleet_locator_id(logical_locator)
        for row in [
            *getattr(self, "_agents_fleet_rows", []),
            *getattr(self, "_agents_fleet_focus_rows", []),
            *getattr(self, "_agents", []),
            *getattr(self, "_agents_with_children", []),
        ]:
            row_locator = getattr(row, "fleet_logical_locator", None)
            if isinstance(row_locator, Mapping) and (
                self._fleet_locator_id(row_locator) == locator_id
            ):
                row.fleet_followed = followed

    def _select_agent_identity_after_projection(
        self,
        identity: tuple[AgentType, str, str | None],
    ) -> None:
        for index, agent in enumerate(getattr(self, "_agents", [])):
            if agent.identity == identity:
                self.current_idx = index
                return

    def _fleet_mode_available(self) -> bool:
        return bool(
            getattr(self, "_agents_fleet_available", False)
            or getattr(self, "_agents_fleet_rows", ())
            or getattr(self, "_agents_fleet_focus_rows", ())
        )

    def _update_agents_header(self) -> None:
        try:
            header = self.query_one("#agents-header")  # type: ignore[attr-defined]
            tabs = self.query_one("#agents-mode-tabs", PanelTabStrip)  # type: ignore[attr-defined]
            status = self.query_one("#agents-fleet-status", Static)  # type: ignore[attr-defined]
        except Exception:
            return

        if not self._fleet_mode_available() and not getattr(
            self,
            "_agents_fleet_loading",
            False,
        ):
            header.add_class("hidden")
            return
        header.remove_class("hidden")
        counts = dict(
            getattr(self, "_agents_fleet_projection", FleetRowsProjection()).counts
        )
        local_count = counts.get(
            "local",
            len(getattr(self, "_agents_local_with_children", [])),
        )
        focus_total = counts.get(
            "focus_total",
            int(local_count) + len(getattr(self, "_agents_fleet_focus_rows", [])),
        )
        fleet_count = counts.get(
            "fleet",
            len(getattr(self, "_agents_fleet_rows", [])),
        )
        tabs.set_tabs(
            (
                PanelTab(
                    "focus",
                    f"Focus {focus_total}",
                    "#5FD7FF",
                    compact_label=f"Focus {focus_total}",
                    micro_label="F",
                    icon="●",
                ),
                PanelTab(
                    "fleet",
                    f"Fleet {fleet_count}",
                    "#D7AF5F",
                    compact_label=f"Fleet {fleet_count}",
                    micro_label="L",
                    icon="◆",
                ),
            ),
            active_tab=self.current_agents_subtab,
        )
        status.update(self._fleet_status_text())

    def _fleet_status_text(self) -> str:
        if getattr(self, "_agents_fleet_loading", False):
            return "loading fleet..."
        error = getattr(self, "_agents_fleet_last_error", None)
        if error:
            return error
        projection = getattr(self, "_agents_fleet_projection", FleetRowsProjection())
        issue_count = len(projection.diagnostics)
        host_count = projection.configured_host_count
        if issue_count:
            suffix = "issue" if issue_count == 1 else "issues"
            return f"{issue_count} {suffix}"
        if host_count:
            suffix = "machine" if host_count == 1 else "machines"
            return f"{host_count} {suffix}"
        return ""

    @staticmethod
    def _fleet_locator_id(locator: Mapping[str, Any]) -> str:
        import json

        try:
            return json.dumps(dict(locator), sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return repr(
                sorted((str(key), repr(value)) for key, value in locator.items())
            )

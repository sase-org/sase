"""Focus/Fleet mode projection and remote hydration for Agents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from textual import on
from textual.widgets import Static

from sase.config import get_machine_name
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
    FollowStoreMutationOutcome,
    FollowStoreSnapshot,
    load_follow_snapshot,
    reconcile_follow_store,
    record_follow,
    unfollow,
)
from sase.feature_flags import FeatureFlag, current_flags

from ...models.fleet_agents import (
    FleetRowsProjection,
    catalog_next_cursors_by_host,
    followed_batch_family_promotions,
    followed_logical_keys,
    merge_catalog_pages,
    project_fleet_agents,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...widgets.panel_tab_strip import PanelTab, PanelTabStrip
from ._fleet_dispatch_launches import AgentFleetDispatchLaunchMixin

if TYPE_CHECKING:
    from ...app import AgentsSubTab
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)

_AGENTS_SUBTABS: tuple[str, str] = ("focus", "fleet")
_FLEET_CATALOG_PAGE_LIMIT = 100
_FLEET_CATALOG_MAX_PAGES = 16
_LOCAL_ACTIVE_STATUSES = frozenset(
    {
        "approved",
        "approval",
        "asking",
        "pending",
        "question",
        "queued",
        "running",
        "starting",
        "waiting",
        "waiting_input",
    }
)
_LOCAL_ATTENTION_STATUSES = frozenset(
    {
        "approval",
        "asking",
        "question",
        "waiting_input",
    }
)


def _unified_agents_enabled() -> bool:
    snapshot = current_flags()
    return snapshot.enabled(FeatureFlag.ace_unified_agents)


def _local_machine_label() -> str:
    try:
        return get_machine_name() or "here"
    except Exception:
        log.debug("local machine name lookup failed", exc_info=True)
        return "here"


def _agent_status_key(agent: Agent) -> str:
    value = getattr(agent, "status_bucket", None) or getattr(agent, "status", "")
    return str(value).casefold().replace("-", "_").replace(" ", "_")


def _agent_counts_as_active(agent: Agent) -> bool:
    return _agent_status_key(agent) in _LOCAL_ACTIVE_STATUSES


def _unified_attention_count(rows: list[Agent]) -> int:
    count = 0
    seen_remote: set[str] = set()
    for agent in rows:
        if getattr(agent, "fleet_origin_alias", None):
            attention = getattr(agent, "fleet_attention", None)
            if not isinstance(attention, Mapping):
                continue
            if str(attention.get("state") or "").casefold() != "pending":
                continue
            key = (
                getattr(agent, "fleet_logical_key", None)
                or getattr(agent, "fleet_exact_key", None)
                or repr(agent.identity)
            )
            if key in seen_remote:
                continue
            seen_remote.add(key)
            count += 1
            continue
        if _agent_status_key(agent) in _LOCAL_ATTENTION_STATUSES:
            count += 1
    return count


def _unified_diagnostic_text(projection: FleetRowsProjection) -> str:
    diagnostics = projection.diagnostics
    if not diagnostics:
        return ""
    aliases = tuple(
        dict.fromkeys(
            str(alias)
            for diagnostic in diagnostics
            if isinstance(diagnostic, Mapping)
            and isinstance(alias := diagnostic.get("alias"), str)
            and alias
        )
    )
    if aliases and len(aliases) <= 2:
        return f"{', '.join(aliases)} unknown"
    issue_count = len(diagnostics)
    suffix = "issue" if issue_count == 1 else "issues"
    return f"{issue_count} machine {suffix}"


class AgentFleetMixin(AgentFleetDispatchLaunchMixin):
    """Remote fleet state, projection, and user actions."""

    current_agents_subtab: AgentsSubTab
    current_tab: str
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agents_local_with_children: list[Agent]
    _agents_fleet_rows: list[Agent]
    _agents_fleet_focus_rows: list[Agent]
    _agents_dispatch_provisional_rows: dict[str, Agent]
    _dispatch_launch_prompt_to_operation: dict[str, str]
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
        if _unified_agents_enabled():
            return
        self._set_agents_subtab(event.tab_id)

    def watch_current_agents_subtab(
        self,
        old_mode: AgentsSubTab,
        new_mode: AgentsSubTab,
    ) -> None:
        """Reproject cached Agents rows when Focus/Fleet mode changes."""
        if old_mode == new_mode:
            return
        if _unified_agents_enabled():
            if new_mode == "fleet":
                self.current_agents_subtab = "focus"
                return
            self._reproject_agents_from_current_mode(source="mode_switch")
            self._schedule_agents_fleet_refresh(
                source="mode_switch",
                force=True,
            )
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
        if _unified_agents_enabled():
            self.notify("Remote agents are already in the unified Agents list")  # type: ignore[attr-defined]
            return
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
        """Open the persistent Machines administration pane."""
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")

    def action_setup_agent_machine(self) -> None:
        """Open enrollment guidance while no remote machine is configured."""
        fleet_available = getattr(self, "_fleet_mode_available", None)
        if callable(fleet_available) and fleet_available():
            self.notify(  # type: ignore[attr-defined]
                "Remote machines are already enrolled; run 'sase machine init' "
                "to rescan, or 'sase machine list' / 'sase machine status' "
                "from a shell for details"
            )
            return
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")
            return
        visible_after_enrollment = (
            "The Agents list includes it once a machine is enrolled."
            if _unified_agents_enabled()
            else "The Focus/Fleet strip appears once a machine is enrolled."
        )
        self.notify(  # type: ignore[attr-defined]
            "No remote machines are enrolled. On the target, run "
            "'sase machine bootstrap --json' into a protected file. On this "
            "controller, run 'sase machine init -B <file>' to discover, enroll, "
            f"and verify. {visible_after_enrollment}",
            timeout=12,
        )

    def _cycle_agents_subtab(self, *, reverse: bool) -> None:
        if _unified_agents_enabled():
            self.notify("Agents already includes enrolled machines")  # type: ignore[attr-defined]
            return
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
        if _unified_agents_enabled():
            self.current_agents_subtab = "focus"
            return
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
        if self.current_agents_subtab == "fleet" and not _unified_agents_enabled():
            return
        self._agents_local_with_children = self._local_agents_from_mixed(
            getattr(self, "_agents_with_children", [])
        )
        self._agents_local_visible = self._local_agents_from_mixed(
            getattr(self, "_agents", [])
        )

    def _agents_source_for_current_mode(self, local_agents: list[Agent]) -> list[Agent]:
        fleet_rows = self._fleet_rows_with_dispatch_provisionals(
            list(getattr(self, "_agents_fleet_rows", []))
        )
        focus_rows = self._fleet_rows_with_dispatch_provisionals(
            list(getattr(self, "_agents_fleet_focus_rows", []))
        )
        if _unified_agents_enabled():
            return [
                *local_agents,
                *fleet_rows,
            ]
        if self.current_agents_subtab == "fleet":
            return fleet_rows
        return [
            *local_agents,
            *focus_rows,
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
            unified_agents = _unified_agents_enabled()
            config = await asyncio.to_thread(load_federation_config)
            follow_snapshot = await asyncio.to_thread(_load_reconciled_follow_snapshot)
            summary_response: Mapping[str, Any] | None = None
            followed_response: Mapping[str, Any] | None = None
            catalog_response: Mapping[str, Any] | None = None
            attention_response: Mapping[str, Any] | None = None
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
                    follow_snapshot = await asyncio.to_thread(
                        _reconcile_followed_batch_family_promotions,
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
                if (
                    unified_agents
                    or self.current_agents_subtab == "fleet"
                    or source == "manual"
                ):
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
        if _unified_agents_enabled():
            self.current_agents_subtab = "focus"
        elif not self._agents_fleet_available and self.current_agents_subtab == "fleet":
            self.current_agents_subtab = "focus"
        self._reproject_agents_from_current_mode(source="fleet_refresh")
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
        self._update_agents_header()

    async def _toggle_agent_follow_async(
        self,
        logical_locator: dict[str, Any],
        *,
        currently_followed: bool,
    ) -> None:
        outcome: FollowStoreMutationOutcome
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
            or getattr(self, "_agents_dispatch_provisional_rows", {})
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
        if _unified_agents_enabled():
            tabs.add_class("hidden")
            status.update(self._unified_agents_status_text())
            return
        tabs.remove_class("hidden")
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

    def _unified_agents_status_text(self) -> str:
        prefix = f"here: {_local_machine_label()}"
        if getattr(self, "_agents_fleet_loading", False):
            return f"{prefix} · loading machines..."
        error = getattr(self, "_agents_fleet_last_error", None)
        if error:
            return f"{prefix} · {error}"
        projection = getattr(self, "_agents_fleet_projection", FleetRowsProjection())
        rows = list(
            getattr(self, "_agents", [])
        ) or self._agents_source_for_current_mode(
            list(getattr(self, "_agents_local_with_children", []))
        )
        active_count = sum(1 for agent in rows if _agent_counts_as_active(agent))
        attention_count = _unified_attention_count(rows)
        host_count = projection.configured_host_count
        parts = [prefix, f"{active_count} active"]
        if attention_count:
            parts.append(f"{attention_count} needs you")
        if host_count:
            suffix = "machine" if host_count == 1 else "machines"
            parts.append(f"{host_count} {suffix}")
        diagnostic_text = _unified_diagnostic_text(projection)
        if diagnostic_text:
            parts.append(diagnostic_text)
        elif projection.partial:
            parts.append("partial")
        return " · ".join(parts)

    def _fleet_status_text(self) -> str:
        if getattr(self, "_agents_fleet_loading", False):
            return "loading fleet..."
        error = getattr(self, "_agents_fleet_last_error", None)
        if error:
            return error
        projection = getattr(self, "_agents_fleet_projection", FleetRowsProjection())
        issue_count = len(projection.diagnostics)
        host_count = projection.configured_host_count
        raw_fleet_count = projection.counts.get("fleet")
        fleet_count = (
            raw_fleet_count
            if isinstance(raw_fleet_count, int)
            else len(projection.fleet_rows)
        )
        partial = bool(projection.partial)
        if issue_count:
            suffix = "issue" if issue_count == 1 else "issues"
            text = f"{issue_count} {suffix}"
            if partial:
                text = f"{text} · partial"
            return text
        if host_count:
            suffix = "machine" if host_count == 1 else "machines"
            text = f"{host_count} {suffix}"
            if partial:
                text = f"{text} · partial"
            if self.current_agents_subtab == "fleet" and fleet_count == 0:
                text = f"{text} · 0 results"
            return text
        if partial:
            return "partial"
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


def _load_reconciled_follow_snapshot() -> FollowStoreSnapshot:
    """Load the follow store, persisting reconciliation when state exists.

    A store with no records or tombstones is left untouched so the
    zero-machine, zero-follow path never writes under the sase home.
    """
    snapshot = load_follow_snapshot()
    if not snapshot.records and not snapshot.tombstones:
        return snapshot
    return reconcile_follow_store().snapshot


def _reconcile_followed_batch_family_promotions(
    snapshot: FollowStoreSnapshot,
    followed_response: Mapping[str, Any] | None,
) -> FollowStoreSnapshot:
    """Persist safe family promotions discovered during followed hydration."""
    promotions = followed_batch_family_promotions(snapshot, followed_response)
    if not promotions:
        return snapshot
    return reconcile_follow_store(promotions=promotions).snapshot

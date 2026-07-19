"""Agents-tab empty-state onboarding helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ...util.pump_tasks import spawn_pump_free_task
from .._widget_visibility import set_widget_hidden, widget_has_class

if TYPE_CHECKING:
    from ...models import Agent
    from ...widgets import AgentDetail, KeybindingFooter

log = logging.getLogger(__name__)


class AgentsOnboardingMixin:
    """Manage the onboarding card shown when no agents are visible."""

    _agents: list[Agent]
    _agents_first_load_done: bool
    _agent_search_query: str
    _agents_onboarding_launch_targets_available: bool
    _agents_onboarding_launch_targets_refresh_scheduled: bool
    _agents_onboarding_launch_targets_refresh_running: bool
    _agents_onboarding_launch_targets_refresh_pending: bool
    _agents_onboarding_plugins_installed: bool
    _agents_onboarding_plugins_refresh_scheduled: bool
    _agents_onboarding_plugins_refresh_running: bool
    _agents_onboarding_plugins_refresh_pending: bool

    if TYPE_CHECKING:

        def _apply_agent_footer_update(
            self,
            agent_detail: AgentDetail,
            footer_widget: KeybindingFooter,
            current_agent: Agent | None,
        ) -> None: ...

    def _should_show_agents_onboarding(self) -> bool:
        """Return True when the Agents tab has no visible rows to select."""
        if not getattr(self, "_agents_first_load_done", False):
            return False
        if (getattr(self, "_agent_search_query", "") or "").strip():
            return False
        return not bool(getattr(self, "_agents", []))

    def _set_agents_onboarding_layout(self, active: bool) -> None:
        """Collapse the Agents-tab chrome while onboarding is visible."""
        from textual.css.query import NoMatches

        try:
            agents_view = self.query_one("#agents-view")  # type: ignore[attr-defined]
        except (NoMatches, LookupError):
            return
        if active:
            agents_view.add_class("-onboarding-active")
        else:
            agents_view.remove_class("-onboarding-active")

    def _schedule_agents_onboarding_launch_targets_refresh(self) -> None:
        """Queue a coalesced off-thread refresh of launch-target availability."""
        if getattr(
            self,
            "_agents_onboarding_launch_targets_refresh_running",
            False,
        ):
            self._agents_onboarding_launch_targets_refresh_pending = True
            return
        if getattr(
            self,
            "_agents_onboarding_launch_targets_refresh_scheduled",
            False,
        ):
            return
        self._agents_onboarding_launch_targets_refresh_scheduled = True
        task = spawn_pump_free_task(
            self,
            self._run_agents_onboarding_launch_targets_refresh(),
            name="sase-agents-onboarding-launch-targets",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._agents_onboarding_launch_targets_refresh_scheduled = False

    async def _run_agents_onboarding_launch_targets_refresh(self) -> None:
        """Compute launch-target availability off-thread and update the card."""
        self._agents_onboarding_launch_targets_refresh_scheduled = False
        self._agents_onboarding_launch_targets_refresh_running = True
        try:
            from ._onboarding_launch_targets import (
                discover_agents_onboarding_launch_targets_available,
            )

            available = await asyncio.to_thread(
                discover_agents_onboarding_launch_targets_available
            )
            self._apply_agents_onboarding_launch_targets_available(available)
        except Exception:
            log.exception("Agents onboarding launch-target refresh failed")
        finally:
            self._agents_onboarding_launch_targets_refresh_running = False
            if self._agents_onboarding_launch_targets_refresh_pending:
                self._agents_onboarding_launch_targets_refresh_pending = False
                self._schedule_agents_onboarding_launch_targets_refresh()

    def _apply_agents_onboarding_launch_targets_available(
        self, available: bool
    ) -> None:
        """Store launch-target availability for the on-demand Help guide."""
        self._agents_onboarding_launch_targets_available = available

    def _schedule_agents_onboarding_plugins_refresh(self) -> None:
        """Queue a coalesced off-thread refresh of plugin presence."""
        if getattr(
            self,
            "_agents_onboarding_plugins_refresh_running",
            False,
        ):
            self._agents_onboarding_plugins_refresh_pending = True
            return
        if getattr(
            self,
            "_agents_onboarding_plugins_refresh_scheduled",
            False,
        ):
            return
        self._agents_onboarding_plugins_refresh_scheduled = True
        task = spawn_pump_free_task(
            self,
            self._run_agents_onboarding_plugins_refresh(),
            name="sase-agents-onboarding-plugins",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._agents_onboarding_plugins_refresh_scheduled = False

    async def _run_agents_onboarding_plugins_refresh(self) -> None:
        """Compute plugin presence off-thread and update the card."""
        self._agents_onboarding_plugins_refresh_scheduled = False
        self._agents_onboarding_plugins_refresh_running = True
        try:
            from ._onboarding_plugins import (
                discover_agents_onboarding_plugins_installed,
            )

            installed = await asyncio.to_thread(
                discover_agents_onboarding_plugins_installed
            )
            self._apply_agents_onboarding_plugins_installed(installed)
        except Exception:
            log.exception("Agents onboarding plugin refresh failed")
        finally:
            self._agents_onboarding_plugins_refresh_running = False
            if self._agents_onboarding_plugins_refresh_pending:
                self._agents_onboarding_plugins_refresh_pending = False
                self._schedule_agents_onboarding_plugins_refresh()

    def _apply_agents_onboarding_plugins_installed(self, installed: bool) -> None:
        """Store plugin presence for the on-demand Help guide."""
        self._agents_onboarding_plugins_installed = installed

    def _sync_agents_onboarding(
        self,
        *,
        agent_detail: AgentDetail | None = None,
        footer_widget: KeybindingFooter | None = None,
    ) -> bool:
        """Toggle the Agents empty-state onboarding panel.

        Returns True when onboarding is visible and callers should skip normal
        detail-panel rendering.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, TabQuickStart

        show_onboarding = self._should_show_agents_onboarding()
        if (
            not show_onboarding
            and agent_detail is not None
            and not widget_has_class(agent_detail, "hidden")
        ):
            return False

        try:
            if agent_detail is None:
                agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            quickstart = self.query_one("#agent-quickstart-panel", TabQuickStart)  # type: ignore[attr-defined]
        except (NoMatches, LookupError):
            return False

        set_widget_hidden(agent_detail, show_onboarding)
        set_widget_hidden(quickstart, not show_onboarding)
        self._set_agents_onboarding_layout(show_onboarding)
        if not show_onboarding:
            return False

        registry = getattr(self, "_keymap_registry", None)
        if registry is not None:
            quickstart.set_keymap_registry(registry)
        else:
            quickstart.refresh_content()
        self._schedule_agents_onboarding_launch_targets_refresh()
        self._schedule_agents_onboarding_plugins_refresh()
        if footer_widget is not None:
            self._apply_agent_footer_update(agent_detail, footer_widget, None)
        return True

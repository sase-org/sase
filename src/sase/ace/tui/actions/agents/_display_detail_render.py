"""Agent detail-panel rendering and refresh-event helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...widgets.prompt_panel._messages import (
    AgentDetailHeaderEnriched,
    ClanSectionSnapshotLoaded,
)
from ._display_helpers import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...tools.report import SlowToolCallReportSpec
    from ...util.debounce import DetailPanelDebouncer
    from ...widgets import AgentDetail, KeybindingFooter
    from ...widgets.prompt_panel._agent_display_state import CommitViewSpec

log = logging.getLogger(__name__)


class AgentDetailRenderMixin:
    """Render and refresh the selected agent's detail panel."""

    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _agent_detail_debouncer: DetailPanelDebouncer
    _hint_mode_active: bool
    _hint_mappings: dict[int, str]
    _hint_commit_views: dict[int, CommitViewSpec]
    _hint_tool_call_reports: dict[str, SlowToolCallReportSpec]

    if TYPE_CHECKING:

        def _sync_agents_onboarding(
            self,
            *,
            agent_detail: AgentDetail | None = None,
            footer_widget: KeybindingFooter | None = None,
        ) -> bool: ...

        def _apply_agent_footer_update(
            self,
            agent_detail: AgentDetail,
            footer_widget: KeybindingFooter,
            current_agent: Agent | None,
        ) -> None: ...

    def _focused_tribe_panel_context(self) -> object | None:
        """Resolve whole-panel focus without constructing its document."""
        for resolver_name in (
            "_resolve_focused_panel",
            "_resolve_focused_collapsed_panel",
        ):
            resolver = getattr(self, resolver_name, None)
            focus = resolver() if callable(resolver) else None
            if focus is not None:
                return focus
        return None

    def _apply_tribe_summary(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter | None = None,
        *,
        cheap: bool = False,
    ) -> bool:
        """Render the live tribe document when whole-panel focus is active."""
        resolver = getattr(self, "_focused_tribe_summary", None)
        snapshot = resolver() if callable(resolver) else None
        if snapshot is None:
            return False
        agent_detail.show_tribe_summary(snapshot, cheap=cheap)
        if footer_widget is not None:
            self._apply_agent_footer_update(agent_detail, footer_widget, None)
        return True

    def _apply_agent_detail_immediate(self) -> bool:
        """Update the detail surface without spawning agent-detail workers.

        Returns True only when no debounced agent-detail phase is required.
        Tribe and clan documents stay on the debounced path because rebuilding
        their multi-section detail on every j/k tick can delay the selection
        highlight's next paint.
        """
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except NoMatches:
            return False

        if self._sync_agents_onboarding(agent_detail=agent_detail):
            return False

        footer_widget = None
        try:
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            pass
        if self._apply_tribe_summary(
            agent_detail,
            footer_widget,
            cheap=True,
        ):
            return False

        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if current_agent is None:
            agent_detail.show_empty()
            return False
        if current_agent.is_clan_container:
            return False
        if self._should_render_agent_detail_with_hints():
            self._render_agent_detail_with_hints(agent_detail, current_agent)
            return False
        agent_detail.update_display_immediate(
            current_agent, attempt_number=self.current_attempt_number
        )
        return False

    def _refresh_agent_focus_detail(self) -> None:
        """Repaint info/detail after a focus change, debouncing real agents."""
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
        if self._apply_agent_detail_immediate():
            self._agent_detail_debouncer.cancel()
            return
        self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)

    def _refresh_tribe_summary_only(self) -> bool:
        """Rebuild only an active tribe after mark/unread state changes."""
        resolver = getattr(self, "_focused_tribe_summary", None)
        snapshot = resolver() if callable(resolver) else None
        if snapshot is None:
            return False
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except NoMatches:
            return False
        agent_detail.show_tribe_summary(snapshot)
        return True

    def _fire_debounced_detail_update(self) -> None:
        """Apply the debounced detail update once the j/k burst quiesces."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("debounced detail update skipped: widget tree unavailable")
            return

        self._apply_agent_detail_update(agent_detail, footer_widget)

    def _apply_agent_detail_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
    ) -> None:
        """Apply the expensive agent detail panel and footer updates.

        Args:
            agent_detail: The agent detail panel widget.
            footer_widget: The keybinding footer widget.
        """
        if self._sync_agents_onboarding(
            agent_detail=agent_detail, footer_widget=footer_widget
        ):
            return

        if self._apply_tribe_summary(agent_detail, footer_widget):
            return

        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if current_agent is not None:
            from ._loading_helpers import hydrate_agent_attempt_history

            changed = (
                False
                if current_agent.is_clan_container
                else hydrate_agent_attempt_history(current_agent)
            )
            if changed:
                self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
            if (
                not current_agent.is_clan_container
                and self._should_render_agent_detail_with_hints()
            ):
                self._render_agent_detail_with_hints(agent_detail, current_agent)
            else:
                agent_detail.update_display(
                    current_agent,
                    stale_threshold_seconds=self.refresh_interval,
                    attempt_number=self.current_attempt_number,
                )
        else:
            agent_detail.show_empty()

        self._apply_agent_footer_update(agent_detail, footer_widget, current_agent)

    def _should_render_agent_detail_with_hints(self) -> bool:
        """Return whether Agents-tab detail repaints must preserve view hints."""
        return (
            self.current_tab == "agents"
            and bool(getattr(self, "_hint_mode_active", False))
            and getattr(self, "_hint_mode_hints_for", None) != "panels"
        )

    def _render_agent_detail_with_hints(
        self,
        agent_detail: AgentDetail,
        current_agent: Agent,
    ) -> None:
        """Render the Agents detail prompt with hints and refresh hint state."""
        hint_render = agent_detail.update_display_with_hints(current_agent)
        self._hint_mappings = hint_render.file_hints
        self._hint_commit_views = hint_render.commit_views
        self._hint_tool_call_reports = hint_render.tool_call_reports

    def on_agent_detail_header_enriched(
        self,
        message: AgentDetailHeaderEnriched,
    ) -> None:
        """Repaint an enriched header without clobbering active view hints."""
        from textual.css.query import NoMatches
        from textual.widgets import Input

        from ...widgets import AgentDetail

        if self._focused_tribe_panel_context() is not None:
            return
        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if current_agent is None or current_agent.identity != message.agent_identity:
            return

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except (NoMatches, KeyError, LookupError):
            return

        if self._should_render_agent_detail_with_hints():
            try:
                hint_input = self.query_one("#hint-input", Input)  # type: ignore[attr-defined]
            except (NoMatches, KeyError, LookupError):
                hint_input = None
            if hint_input is None or not hint_input.value:
                self._render_agent_detail_with_hints(agent_detail, current_agent)
        else:
            agent_detail.refresh_detail_header_from_cache(current_agent)
        message.stop()

    def on_clan_section_snapshot_loaded(
        self,
        message: ClanSectionSnapshotLoaded,
    ) -> None:
        """Debounce the repaint for a current clan enrichment result."""
        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if (
            current_agent is None
            or not current_agent.is_clan_container
            or current_agent.identity != message.agent_identity
        ):
            return
        self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
        message.stop()

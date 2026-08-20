"""Agent detail-panel rendering and refresh-event helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...util.trace import tui_trace
from ...widgets.prompt_panel._messages import (
    AgentDetailHeaderEnriched,
    ClanSectionSnapshotLoaded,
    TribeSectionSnapshotLoaded,
)
from ._display_helpers import TabName

if TYPE_CHECKING:
    from sase.glossary.read_report import GlossaryReadReportSpec

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
    _hint_glossary_reports: dict[str, GlossaryReadReportSpec]

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
        snapshot = resolver(with_entry_target=not cheap) if callable(resolver) else None
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

    def watch_theme(self, old: str | None = None, new: str | None = None) -> None:
        """Rebuild authored-prompt caches so theme-derived colors cannot go stale."""
        try:
            parent = getattr(super(), "watch_theme", None)
        except TypeError:
            parent = None
        if callable(parent):
            parent(old, new)
        if getattr(self, "current_tab", None) != "agents":
            return
        self._refresh_agent_focus_detail(render_immediate=False)

    def _refresh_agent_focus_detail(self, *, render_immediate: bool = True) -> None:
        """Repaint info/detail after focus changes and debounce full documents.

        Selected-tribe ``j``/``k`` navigation suppresses even the cheap
        prompt repaint: changing that document forces a layout before the
        selected-panel chrome can paint. Other focus transitions retain the
        immediate header path.

        Runtime-state init assigns ``theme`` while ``current_tab`` is already
        ``agents`` and before the detail debouncer exists; skip until then so
        the first theme application cannot schedule a timer or crash.
        """
        debouncer = getattr(self, "_agent_detail_debouncer", None)
        if debouncer is None:
            return
        if not render_immediate:
            debouncer.schedule(self._fire_debounced_detail_update)
            return
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
        if self._apply_agent_detail_immediate():
            debouncer.cancel()
            return
        debouncer.schedule(self._fire_debounced_detail_update)

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
        nav_gate = getattr(self, "_nav_gate", None)
        is_navigating = getattr(nav_gate, "is_navigating", None)
        if callable(is_navigating) and is_navigating():
            # The 150 ms detail timer can land between individually painted
            # keys while the wider navigation activity window is still open.
            # Keep this pump callback thin and try again after another quiet
            # interval instead of laying out a document mid-navigation.
            self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
            return
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
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
            if self._should_render_agent_detail_with_hints():
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
        """Return whether Agents-tab detail repaints preserve active hints."""
        return self.current_tab == "agents" and bool(
            getattr(self, "_hint_mode_active", False)
        )

    def _render_agent_detail_with_hints(
        self,
        agent_detail: AgentDetail,
        current_agent: Agent,
    ) -> None:
        """Render the Agents detail prompt with hints and refresh hint state."""
        ready = getattr(self, "_agent_hint_render_ready", None)
        if ready is not None and not ready.is_set():
            return
        with tui_trace("agents.view_hints_refresh") as extra:
            extra["family_container"] = current_agent.is_family_container_row
            is_current = getattr(agent_detail, "hint_document_is_current", None)
            if callable(is_current) and is_current(current_agent):
                extra["cache"] = "current"
                return
            hint_render = agent_detail.update_display_with_hints(current_agent)
            extra["cache"] = "rebuilt"
            extra["hints"] = len(hint_render.file_hints)
            extra["commit_views"] = len(hint_render.commit_views)
            self._hint_mappings = hint_render.file_hints
            self._hint_commit_views = hint_render.commit_views
            self._hint_tool_call_reports = hint_render.tool_call_reports
            self._hint_glossary_reports = hint_render.glossary_reports

    def on_agent_detail_header_enriched(
        self,
        message: AgentDetailHeaderEnriched,
    ) -> None:
        """Repaint an enriched header without clobbering active view hints.

        Detail-header enrichment now publishes once per resolved lane batch
        (bead sase-l6.4) rather than once at the very end, so this handler
        can fire several times for one selection. The non-hint branch
        routes the repaint through the shared detail debouncer -- the same
        mechanism ``on_clan_section_snapshot_loaded`` already uses below --
        so a burst of batch publishes collapses to one paint instead of
        rebuilding the document per batch. The hint-mode branch stays
        immediate (hint numbering must never lag what is on screen) but
        gains a second escape hatch: even with a typed hint value, a
        publish that finished the *last* lane is still allowed through, so
        a hint session started mid-stream is not stuck on a partial
        document until the user clears the input.
        """
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
            hint_empty = hint_input is None or not hint_input.value
            if hint_empty or agent_detail.detail_header_summary_complete(current_agent):
                self._render_agent_detail_with_hints(agent_detail, current_agent)
        else:
            self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
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

    def on_tribe_section_snapshot_loaded(
        self,
        message: TribeSectionSnapshotLoaded,
    ) -> None:
        """Debounce repaint only while the enriched tribe remains focused."""
        focus = self._focused_tribe_panel_context()
        if (
            focus is None
            or getattr(focus, "container_identity", None) != message.panel_identity
        ):
            return
        self._agent_detail_debouncer.schedule(self._fire_debounced_detail_update)
        message.stop()

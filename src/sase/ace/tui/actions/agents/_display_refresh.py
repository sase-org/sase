"""Full and debounced refresh for the agent display mixin."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget

from ...util.debounce import DetailPanelDebouncer
from ...util.trace import tui_trace
from ._paint_log import record_agents_paint_frame
from ._refresh_trace import (
    AgentRefreshDisplayCost,
    record_agents_refresh_trace,
)

log = logging.getLogger(__name__)


class AgentDisplayRefreshMixin:
    """Top-level refresh entry points for the agents tab."""

    _agents: list[Agent]
    _agent_detail_debouncer: DetailPanelDebouncer
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    _entry_jump_banner_to_hint: dict[BannerJumpTarget, str]
    _entry_jump_panel_to_hint: dict[PanelJumpTarget, str]

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        """Refresh the agents tab display.

        Args:
            list_changed: If True, the agent list has changed and needs a full
                rebuild (called from _load_agents). If False, only the selection
                index moved (j/k navigation) — skip the expensive OptionList
                clear-and-rebuild.
        """
        source = getattr(self, "_agents_refresh_active_source", "unknown")
        display_cost: AgentRefreshDisplayCost | None = (
            "display_full_rebuild" if list_changed else None
        )
        if display_cost is not None:
            record_agents_refresh_trace(
                self,
                stage="display",
                source=source,
                display_cost=display_cost,
                agents=len(self._agents),
                defer_detail=defer_detail,
            )
        with tui_trace(
            "agents.refresh_display",
            agents=len(self._agents),
            list_changed=bool(list_changed),
            defer_detail=bool(defer_detail),
            source=source,
            display_cost=display_cost,
        ):
            self._refresh_agents_display_impl(
                list_changed=list_changed, defer_detail=defer_detail
            )
        record_agents_paint_frame(
            self, kind="full_rebuild" if list_changed else "highlight"
        )

    def _refresh_agents_display_impl(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        started = time.perf_counter()
        list_started = started
        sync_artifact_layout = getattr(self, "_sync_artifact_file_viewer_layout", None)
        if callable(sync_artifact_layout):
            sync_artifact_layout()
        # Cancel any pending debounced detail update — full refresh supersedes
        self._agent_detail_debouncer.cancel()

        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("agents display refresh skipped: widget tree unavailable")
            return

        if list_changed:
            # Drop any marks pointing at identities that no longer exist.
            self._prune_stale_marked_agents()  # type: ignore[attr-defined]
            self._sync_panel_group()  # type: ignore[attr-defined]
            self._snap_focus_after_agents_fold_restore()  # type: ignore[attr-defined]
            ensure_jump_current = getattr(
                self, "_ensure_agents_jump_maps_current", None
            )
            if callable(ensure_jump_current):
                try:
                    ensure_jump_current()
                except Exception:
                    pass
            jump_hints = (
                dict(self._entry_jump_index_to_hint)
                if self._entry_jump_mode_active
                else None
            )
            banner_jump_hints = (
                dict(self._entry_jump_banner_to_hint)
                if self._entry_jump_mode_active
                else None
            )
            panel_jump_hints = (
                dict(self._entry_jump_panel_to_hint)
                if self._entry_jump_mode_active
                else None
            )
            if not self._entry_jump_mode_active and getattr(
                self, "_panel_fold_hint_mode_active", False
            ):
                (
                    jump_hints,
                    banner_jump_hints,
                ) = self._panel_fold_hint_display_maps()  # type: ignore[attr-defined]
                panel_jump_hints = self._panel_fold_hint_title_map() or None  # type: ignore[attr-defined]

            self._refresh_panel_widgets(  # type: ignore[attr-defined]
                jump_hints=jump_hints,
                banner_jump_hints=banner_jump_hints,
                panel_jump_hints=panel_jump_hints,
            )
            log.debug(
                "agents display refresh list phase: elapsed=%.3fs agents=%d",
                time.perf_counter() - list_started,
                len(self._agents),
            )
        else:
            self._refresh_panel_highlights()  # type: ignore[attr-defined]

        self._update_agents_info_panel()  # type: ignore[attr-defined]
        update_agents_header = getattr(self, "_update_agents_header", None)
        if callable(update_agents_header):
            update_agents_header()
        if defer_detail:
            if self._sync_agents_onboarding(  # type: ignore[attr-defined]
                agent_detail=agent_detail, footer_widget=footer_widget
            ):
                log.debug(
                    "agents display refresh onboarding detail: elapsed=%.3fs",
                    time.perf_counter() - started,
                )
                return
            if self._apply_tribe_summary(  # type: ignore[attr-defined]
                agent_detail,
                footer_widget,
                cheap=True,
            ):
                self._agent_detail_debouncer.schedule(
                    self._fire_debounced_detail_update  # type: ignore[attr-defined]
                )
                log.debug(
                    "agents display refresh tribe summary: elapsed=%.3fs",
                    time.perf_counter() - started,
                )
                return
            self._agent_detail_debouncer.schedule(
                self._fire_debounced_detail_update  # type: ignore[attr-defined]
            )
            log.debug(
                "agents display refresh deferred detail: elapsed=%.3fs",
                time.perf_counter() - started,
            )
            return

        detail_started = time.perf_counter()
        self._apply_agent_detail_update(agent_detail, footer_widget)  # type: ignore[attr-defined]
        log.debug(
            "agents display refresh detail phase: elapsed=%.3fs total=%.3fs",
            time.perf_counter() - detail_started,
            time.perf_counter() - started,
        )

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Two-phase: the immediate phase updates list highlight, info panel,
        and the detail prompt header for the freshly-selected agent. The
        debounced phase fires after the j/k burst settles and runs the
        expensive file/LLM Calls/diff workers — only for the final selection.
        """
        with tui_trace("agents.refresh_debounced", agents=len(self._agents)):
            self._refresh_panel_highlights()  # type: ignore[attr-defined]
            self._update_agents_info_panel()  # type: ignore[attr-defined]
            if self._apply_agent_detail_immediate():  # type: ignore[attr-defined]
                self._agent_detail_debouncer.cancel()
            else:
                self._agent_detail_debouncer.schedule(
                    self._fire_debounced_detail_update  # type: ignore[attr-defined]
                )


__all__ = ["AgentDisplayRefreshMixin"]

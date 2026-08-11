"""Agent detail-panel footer binding helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sase.agent.status_buckets import agent_is_asking

from ...models.agent_hoods import agent_owns_lane
from ._display_helpers import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...widgets import AgentDetail, KeybindingFooter

log = logging.getLogger(__name__)


class AgentFooterDisplayMixin:
    """Refresh footer bindings for the current agent detail state."""

    current_attempt_number: int | None
    current_tab: TabName
    _current_group_key: tuple[str, ...] | None
    _marked_agents: set[tuple[AgentType, str, str | None]]

    if TYPE_CHECKING:

        def _selected_agent_neighbor_count(
            self, current_agent: Agent | None
        ) -> int: ...

        def _selected_agent_tmux_choice_count(
            self, current_agent: Agent | None
        ) -> int: ...

    def _apply_agent_footer_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
        current_agent: Agent | None,
    ) -> None:
        """Refresh Agents-tab footer bindings for the current selection."""
        if self.current_tab != "agents":
            return
        if pending_digit := getattr(self, "_member_jump_pending_digit", None):
            footer_widget.update_member_jump_bindings(pending_digit)
        elif getattr(self, "_fold_mode_active", False):
            scale_resolver = getattr(self, "_selected_summary_fold_scale", None)
            fold_scale = scale_resolver() if callable(scale_resolver) else None
            footer_widget.update_fold_bindings(
                current_tab="agents",
                fold_scale=fold_scale,
            )
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings(
                current_tab="agents",
                has_notification=(
                    agent_is_asking(current_agent.status)
                    if current_agent is not None
                    else False
                ),
                has_unread_completed_agent=self._has_unread_completed_agent(),  # type: ignore[attr-defined]
                has_bulk_read_undo_available=self._has_bulk_read_undo_available(),  # type: ignore[attr-defined]
                has_stopped_agent=self._has_stopped_agent(),  # type: ignore[attr-defined]
            )
        elif getattr(self, "_bang_mode_active", False):
            footer_widget.update_bang_bindings()
        elif getattr(self, "_copy_mode_active", False):
            file_visible = agent_detail.is_file_visible()
            footer_widget.update_copy_bindings(
                self.current_tab,
                artifacts_pane_key=getattr(self, "current_artifacts_pane_key", None),
                file_visible=file_visible,
            )
        elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
            footer_widget.update_custom_mode_bindings(cm)
        else:
            completed_count = self._agent_panel_index().completed_count  # type: ignore[attr-defined]
            can_jump = (
                not current_agent.is_clan_container
                and self._resolve_agent_cl_name(current_agent) is not None  # type: ignore[attr-defined]
                if current_agent
                else False
            )
            cached_artifacts = getattr(self, "_cached_artifact_files", None)
            if (
                current_agent is not None
                and not current_agent.is_clan_container
                and callable(cached_artifacts)
            ):
                probe = cached_artifacts(current_agent)
                if probe is None:
                    schedule = getattr(self, "_schedule_artifact_file_discovery", None)
                    if callable(schedule):
                        schedule(current_agent)
                    has_artifact_files = False
                else:
                    has_artifact_files = bool(probe)
            else:
                has_artifact_files = False
            artifact_visible = getattr(self, "_artifact_file_tmux_pane_visible", None)
            artifact_file_viewer_active = (
                bool(artifact_visible()) if callable(artifact_visible) else False
            )
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            panel_focused = panel_focus is not None
            panel_collapsed = bool(panel_focus is not None and panel_focus.collapsed)
            resolve_last_expanded = getattr(
                self, "_resolve_last_expanded_panel_target", None
            )
            panel_collapse_jump_available = bool(
                panel_collapsed
                and callable(resolve_last_expanded)
                and resolve_last_expanded() is not None
            )
            isolation_revert = getattr(self, "_panel_isolation_revert_record", None)
            panel_restore_armed = bool(
                callable(isolation_revert) and isolation_revert() is not None
            )
            panel_group = getattr(self, "_panel_group", None)
            panel_isolation_available = bool(
                panel_group is not None
                and not getattr(self, "_agent_panels_grouped", False)
                and len(panel_group.panel_keys) >= 2
            )
            panel_fold_sweep_available = False
            panel_fold_restore_armed = False
            if panel_group is not None and not panel_collapsed:
                sweep_panel_key = (
                    panel_focus.panel_key
                    if panel_focus is not None
                    else panel_group.focused_key
                )
                has_collapsible = getattr(self, "_panel_has_collapsible_folds", None)
                if callable(has_collapsible):
                    panel_fold_sweep_available = bool(has_collapsible(sweep_panel_key))
                if not panel_fold_sweep_available:
                    restore_available = getattr(
                        self, "_panel_fold_sweep_restore_available", None
                    )
                    if callable(restore_available):
                        panel_fold_restore_armed = bool(
                            restore_available(sweep_panel_key)
                        )
            tools_visible = agent_detail.is_tools_visible()
            left_navigation_kind: str | None = None
            resolve_left_navigation = getattr(
                self, "_resolve_agent_left_navigation_target", None
            )
            if not panel_focused and callable(resolve_left_navigation):
                left_navigation = resolve_left_navigation()
                if left_navigation is not None:
                    left_navigation_kind = left_navigation.kind

            # Under whole-panel focus, ``H`` arms a hinted collapse instead of
            # the row-scoped ladder below, so these resolvers stay row-only;
            # each already returns ``None`` while a panel holds focus.
            lane_collapse_available = False
            resolve_lane_collapse = getattr(
                self, "_resolve_agent_lane_collapse_target", None
            )
            if (
                not tools_visible
                and not panel_focused
                and callable(resolve_lane_collapse)
            ):
                lane_collapse_available = resolve_lane_collapse() is not None

            clan_target = None
            resolve_clan_collapse = getattr(
                self, "_resolve_agent_clan_collapse_target", None
            )
            if (
                not tools_visible
                and not panel_focused
                and not lane_collapse_available
                and callable(resolve_clan_collapse)
            ):
                clan_target = resolve_clan_collapse()
            clan_collapse_available = clan_target is not None
            selected_clan_collapse_available = False
            if clan_target is not None:
                narrow_clan_collapse = getattr(
                    self,
                    "_narrow_agent_clan_collapse_target_to_selection",
                    None,
                )
                selected_clan_collapse_available = bool(
                    callable(narrow_clan_collapse)
                    and narrow_clan_collapse(clan_target) is not None
                )

            structural_collapse_kind: str | None = None
            resolve_structural_collapse = getattr(
                self, "_resolve_agent_structural_collapse_target", None
            )
            if (
                not tools_visible
                and not panel_focused
                and not lane_collapse_available
                and not clan_collapse_available
                and callable(resolve_structural_collapse)
            ):
                structural_collapse = resolve_structural_collapse()
                if structural_collapse is not None:
                    structural_collapse_kind = structural_collapse.kind

            group_collapse_available = False
            resolve_group_collapse = getattr(
                self, "_resolve_group_collapse_target", None
            )
            if (
                not tools_visible
                and not panel_focused
                and not lane_collapse_available
                and not clan_collapse_available
                and structural_collapse_kind is None
                and callable(resolve_group_collapse)
            ):
                group_collapse_available = resolve_group_collapse() is not None
            neighbor_count = (
                0
                if current_agent is not None and current_agent.is_clan_container
                else self._selected_agent_neighbor_count(current_agent)
            )
            footer_widget.update_agent_bindings(
                current_agent,
                completed_count=completed_count,
                can_jump_to_patch=can_jump,
                marked_count=len(self._marked_agents),
                attempt_pinned=self.current_attempt_number is not None,
                panel_focused=panel_focused,
                panel_collapsed=panel_collapsed,
                panel_collapse_jump_available=panel_collapse_jump_available,
                panel_restore_armed=panel_restore_armed,
                panel_isolation_available=panel_isolation_available,
                panel_fold_sweep_available=panel_fold_sweep_available,
                panel_fold_restore_armed=panel_fold_restore_armed,
                left_navigation_kind=left_navigation_kind,
                lane_collapse_available=lane_collapse_available,
                clan_collapse_available=clan_collapse_available,
                selected_clan_collapse_available=selected_clan_collapse_available,
                structural_collapse_kind=structural_collapse_kind,
                group_collapse_available=group_collapse_available,
                focused_panel_key=(
                    panel_focus.panel_key if panel_focus is not None else None
                ),
                group_focused=self._current_group_key is not None,
                has_artifact_files=has_artifact_files,
                artifact_file_viewer_active=artifact_file_viewer_active,
                lane_neighbor_jump_available=(
                    current_agent is not None
                    and agent_owns_lane(current_agent)
                    and not current_agent.is_family_container_row
                    and neighbor_count > 0
                ),
                neighbor_count=neighbor_count,
                tmux_choice_count=(
                    0
                    if current_agent is not None and current_agent.is_clan_container
                    else self._selected_agent_tmux_choice_count(current_agent)
                ),
                tools_visible=tools_visible,
                tools_detail_level=int(agent_detail.tools_detail_level),
            )

    def _refresh_agent_footer_bindings_only(self) -> None:
        """Refresh footer bindings without rebuilding the agent detail panel."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("footer-only update skipped: widget tree unavailable")
            return
        self._apply_agent_footer_update(
            agent_detail,
            footer_widget,
            self._get_selected_agent(),  # type: ignore[attr-defined]
        )

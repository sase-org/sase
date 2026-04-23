"""Render mixin for the ace axe display.

Paints the axe dashboard, info panel, side-panel list, keybinding footer,
and footer-state indicators from the in-memory caches populated by
``AxeDisplayLoadersMixin``.
"""

from __future__ import annotations

from ...bgcmd import get_slot_info, is_slot_running
from ...widgets.bgcmd_list import BgCmdItem
from ._loaders import AxeDisplayLoadersMixin


class AxeDisplayRenderMixin(AxeDisplayLoadersMixin):
    """Mixin providing the axe display rendering and state-setter methods."""

    def _refresh_axe_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the axe tab.

        Updates the side-panel highlight and info-panel position counter
        immediately, then schedules the full dashboard/info-panel redraw on
        a 150 ms timer. Rapid bursts of navigation collapse to a single
        final render.
        """
        from ...widgets import BgCmdList

        # Derive the selection so the info panel counter is accurate even
        # before the debounce fires.
        self._derive_axe_view_from_selection()

        try:
            bgcmd_list = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
            bgcmd_list.update_highlight(self.current_idx)
        except Exception:
            pass

        # Update position counter on the info panel immediately so the
        # "N/M" indicator keeps up with j/k even if the panel redraw is
        # debounced.
        self._update_axe_info_panel()

        # Cancel any pending debounce timer before scheduling a new one.
        if self._axe_detail_update_timer is not None:
            self._axe_detail_update_timer.stop()

        self._axe_detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
            0.15, self._fire_debounced_axe_refresh
        )

    def _fire_debounced_axe_refresh(self) -> None:
        """Timer callback for the debounced axe refresh."""
        self._axe_detail_update_timer = None
        self._refresh_axe_display()

    def _refresh_axe_display(self) -> None:
        """Refresh the axe dashboard display."""
        from textual.containers import VerticalScroll

        from ...widgets import AxeDashboard, AxeInfoPanel, BgCmdList, KeybindingFooter

        # Derive current view from selected item
        self._derive_axe_view_from_selection()

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]

            # Update countdown
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Update info panel based on current view. All reads are from the
            # in-memory cache populated by the async collector; navigation must
            # never hit disk.
            if self._axe_current_view == "axe":
                if self._axe_lumberjack_idx is not None and self._axe_lumberjack_names:
                    # Show lumberjack-specific view
                    lumberjack_name = self._axe_lumberjack_names[
                        self._axe_lumberjack_idx
                    ]
                    lumberjack_output = self._axe_lumberjack_log_tails.get(
                        lumberjack_name, ""
                    )
                    lumberjack_status = self._axe_lumberjack_statuses.get(
                        lumberjack_name
                    )
                    lumberjack_idx = self._axe_lumberjack_idx
                    lumberjack_total = len(self._axe_lumberjack_names)

                    axe_info.update_lumberjack_status(
                        lumberjack_name, lumberjack_idx, lumberjack_total
                    )
                    axe_dashboard.update_lumberjack_display(
                        name=lumberjack_name,
                        idx=lumberjack_idx,
                        total=lumberjack_total,
                        status=lumberjack_status,
                        output=lumberjack_output,
                        countdown=self._countdown_remaining,
                    )
                else:
                    # Show main axe page with lumberjack activity summary
                    axe_info.update_status(self.axe_running)

                    # Get full cycles from metrics if available
                    full_cycles = 0
                    if self._axe_metrics:
                        full_cycles = self._axe_metrics.full_cycles_run

                    # Gather lumberjack summaries from the cache
                    from sase.axe.state import LumberjackStatus

                    lumberjack_summaries: list[
                        tuple[str, LumberjackStatus | None, int]
                    ] = []
                    for lumberjack_name in self._axe_lumberjack_names:
                        lumberjack_status = self._axe_lumberjack_statuses.get(
                            lumberjack_name
                        )
                        lumberjack_metrics_entry = self._axe_lumberjack_metrics.get(
                            lumberjack_name
                        )
                        chops_executed = (
                            lumberjack_metrics_entry.chops_executed
                            if lumberjack_metrics_entry
                            else 0
                        )
                        lumberjack_summaries.append(
                            (lumberjack_name, lumberjack_status, chops_executed)
                        )

                    axe_dashboard.update_display(
                        is_running=self.axe_running,
                        status=self._axe_status,
                        output=self._axe_output,
                        full_cycles=full_cycles,
                        countdown=self._countdown_remaining,
                        lumberjack_summaries=lumberjack_summaries,
                    )
            else:
                # Showing a bgcmd view — paint from cache when available. On a
                # cold miss we fall back to the quick non-I/O reads (info +
                # running) so the header still renders; the log panel shows an
                # empty string until the async collector lands.
                slot = self._axe_current_view
                snapshot = self._axe_bgcmd_details.get(slot)
                if snapshot is not None:
                    info = snapshot.info
                    running = snapshot.running
                    output = snapshot.output_tail
                else:
                    info = get_slot_info(slot)
                    running = is_slot_running(slot)
                    output = ""

                axe_info.update_bgcmd_status(slot, info, running)
                axe_dashboard.update_bgcmd_display(
                    info, output, running, self._countdown_remaining
                )

            from ...modals import get_runner_count

            footer.set_axe_running(self.axe_running)
            running_count, done_count = self._get_bgcmd_counts()
            footer.set_bgcmd_count(running_count, done_count)
            footer.set_runner_count(get_runner_count())
            if getattr(self, "_fold_mode_active", False):
                footer.update_fold_bindings()
            elif getattr(self, "_leader_mode_active", False):
                footer.update_leader_bindings(current_tab="axe")
            elif getattr(self, "_bang_mode_active", False):
                footer.update_bang_bindings()
            elif getattr(self, "_copy_mode_active", False):
                footer.update_copy_bindings(self.current_tab)
            elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
                footer.update_custom_mode_bindings(cm)
            else:
                selected_slot_done = False
                if 0 <= self.current_idx < len(self._axe_items):
                    sel_item = self._axe_items[self.current_idx]
                    if isinstance(sel_item, BgCmdItem):
                        sel_snapshot = self._axe_bgcmd_details.get(sel_item.slot)
                        if sel_snapshot is not None:
                            selected_slot_done = not sel_snapshot.running
                        else:
                            selected_slot_done = not is_slot_running(sel_item.slot)
                footer.update_axe_bindings(
                    axe_current_view=self._axe_current_view,
                    selected_slot_done=selected_slot_done,
                )

            # Always update the side-panel list. Pass cached statuses and
            # running flags so the side-panel render path does no disk I/O.
            try:
                bgcmd_list = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
                bgcmd_running_cache = {
                    slot: snap.running for slot, snap in self._axe_bgcmd_details.items()
                }
                bgcmd_list.update_list(
                    items=self._axe_items,
                    current_idx=self.current_idx,
                    axe_running=self.axe_running,
                    lumberjack_names=self._axe_lumberjack_names,
                    bgcmd_infos=dict(self._bgcmd_slots),
                    jump_hints=(
                        self._entry_jump_index_to_hint
                        if self._entry_jump_mode_active
                        else None
                    ),
                    lumberjack_statuses=self._axe_lumberjack_statuses,
                    bgcmd_running=bgcmd_running_cache,
                )
            except Exception:
                pass

            # Auto-scroll to bottom if pinned and on axe view
            if self._axe_pinned_to_bottom and self._axe_current_view == "axe":
                scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
                scroll_container.scroll_end(animate=False)
        except Exception:
            # Widget not found, possibly not on axe tab
            pass

    def _update_axe_info_panel(self) -> None:
        """Update the axe info panel and dashboard status bar with countdown."""
        from ...widgets import AxeDashboard, AxeInfoPanel

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            if self._axe_current_view == "axe":
                axe_info.update_status(self.axe_running)
            else:
                slot = self._axe_current_view
                snapshot = self._axe_bgcmd_details.get(slot)
                if snapshot is not None:
                    info = snapshot.info
                    running = snapshot.running
                else:
                    info = get_slot_info(slot)
                    running = is_slot_running(slot)
                axe_info.update_bgcmd_status(slot, info, running)
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Also update dashboard status bar countdown
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            axe_dashboard.update_countdown(self._countdown_remaining)
        except Exception:
            pass

    def _update_axe_keybinding(self) -> None:
        """Update the keybinding footer with current axe state."""
        from ...widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_running(self.axe_running)
            footer.set_bgcmd_count(running_count, done_count)
        except Exception:
            pass

    def _set_axe_starting(self, starting: bool) -> None:
        """Set axe starting state and update footer.

        Args:
            starting: Whether axe is currently starting up.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_starting(starting)
        except Exception:
            pass

    def _set_axe_stopping(self, stopping: bool) -> None:
        """Set axe stopping state and update footer.

        Args:
            stopping: Whether axe is currently stopping.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_stopping(stopping)
        except Exception:
            pass

    def _set_axe_restarting(self, restarting: bool) -> None:
        """Set axe restarting state and update footer.

        Args:
            restarting: Whether axe is currently restarting.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_restarting(restarting)
        except Exception:
            pass

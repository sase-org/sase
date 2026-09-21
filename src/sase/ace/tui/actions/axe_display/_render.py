"""Render mixin for the ace axe display.

Paints the axe dashboard, info panel, side-panel list, keybinding footer,
and footer-state indicators from the in-memory caches populated by
``AxeDisplayLoadersMixin``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem, ServiceProcItem
from ._loaders import AxeDisplayLoadersMixin

if TYPE_CHECKING:
    from ...keymaps import KeymapRegistry
    from ._data import ChopSnapshot


def _chop_allows_auto_scroll(snapshot: ChopSnapshot | None, run_idx: int) -> bool:
    """Return whether a selected chop run should keep following its tail."""
    if snapshot is None or not snapshot.runs:
        return False
    selected = snapshot.runs[max(0, min(run_idx, len(snapshot.runs) - 1))]
    return selected.entry.status in {"running", "launched"}


class AxeDisplayRenderMixin(AxeDisplayLoadersMixin):
    """Mixin providing the axe display rendering and state-setter methods."""

    _keymap_registry: KeymapRegistry

    def _axe_step_chop_run(self, *, direction: int) -> None:
        """Cycle the displayed run for the selected chop.

        ``direction == 1`` moves toward older runs (Ctrl+N); ``-1`` toward
        newer runs (Ctrl+P). No-op on lumberjack and bgcmd rows, or when
        the selected chop has no recorded runs. Repaints from cache only —
        never reads from disk.
        """
        if self.current_tab != "services":
            return
        # Make sure the derived chop-selection field reflects what the user
        # is actually pointing at; navigation may have happened before the
        # debounced refresh fired.
        self._derive_axe_view_from_selection()
        if not self._axe_step_chop_run_offset(direction):
            return
        self._refresh_axe_display()

    def _refresh_axe_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the axe tab.

        Updates the side-panel highlight and info-panel position counter
        immediately, then schedules the full dashboard/info-panel redraw
        through the shared debouncer so rapid bursts collapse to a single
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
        self._axe_detail_debouncer.schedule(self._refresh_axe_display)  # type: ignore[attr-defined]

    def _refresh_axe_display(self) -> None:
        """Refresh the axe dashboard display."""
        from textual.containers import VerticalScroll

        from ...widgets import AxeDashboard, AxeInfoPanel, BgCmdList, KeybindingFooter

        # Derive current view from selected item
        self._derive_axe_view_from_selection()
        self._axe_ensure_selected_service_tail()
        self._axe_ensure_selected_chop_tails()

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]

            # Update countdown
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Update info panel based on current view. All reads are from the
            # in-memory cache populated by the async collector; navigation must
            # never hit disk.
            service_snapshot = getattr(self, "_service_status", None)
            axe_info.update_host_chrome(
                None if service_snapshot is None else service_snapshot.host,
            )
            if self._axe_current_view == "axe":
                service_selection = self._axe_service_selection
                chop_selection = self._axe_chop_selection
                if service_selection is not None:
                    service_snapshot = self._service_status
                    procs = () if service_snapshot is None else service_snapshot.procs
                    proc = next(
                        (item for item in procs if item.name == service_selection),
                        None,
                    )
                    service_idx = next(
                        (
                            idx
                            for idx, item in enumerate(procs)
                            if item.name == service_selection
                        ),
                        0,
                    )
                    axe_info.update_service_status(
                        name=service_selection,
                        idx=service_idx,
                        total=len(procs),
                        proc=proc,
                    )
                    axe_dashboard.update_service_proc_display(
                        snapshot=service_snapshot,
                        proc=proc,
                        name=service_selection,
                        output=self._service_log_tails.get(service_selection, ""),
                        countdown=self._countdown_remaining,
                    )
                elif chop_selection is not None:
                    # Chop child row selected → chop-run-detail view.
                    lj_name, chop_name = chop_selection
                    from ._data import ChopSnapshot

                    chop_snap = self._axe_chop_snapshots.get(chop_selection)
                    if chop_snap is None:
                        # Cache miss (e.g. config changed mid-flight): fall
                        # back to an empty snapshot so the panel still paints.
                        chop_snap = ChopSnapshot(
                            lumberjack_name=lj_name,
                            chop_name=chop_name,
                            description="",
                            runs=[],
                        )
                    run_idx = self._axe_resolve_chop_run_offset(chop_selection)
                    axe_info.update_chop_status(
                        lumberjack_name=lj_name,
                        chop_name=chop_name,
                        run_idx=run_idx,
                        run_total=len(chop_snap.runs),
                    )
                    axe_dashboard.update_chop_run_display(
                        snapshot=chop_snap,
                        run_idx=run_idx,
                        countdown=self._countdown_remaining,
                    )
                elif (
                    self._axe_lumberjack_idx is not None and self._axe_lumberjack_names
                ):
                    # Lumberjack row selected → lumberjack overview view.
                    lumberjack_name = self._axe_lumberjack_names[
                        self._axe_lumberjack_idx
                    ]
                    lumberjack_idx = self._axe_lumberjack_idx
                    lumberjack_total = len(self._axe_lumberjack_names)

                    from ._data import LumberjackSnapshot

                    jack_snap = self._axe_lumberjack_snapshots.get(lumberjack_name)
                    if jack_snap is None:
                        jack_snap = LumberjackSnapshot(
                            name=lumberjack_name,
                            description="",
                            status=self._axe_lumberjack_statuses.get(lumberjack_name),
                            metrics=self._axe_lumberjack_metrics.get(lumberjack_name),
                            log_tail=self._axe_lumberjack_log_tails.get(
                                lumberjack_name, ""
                            ),
                            chops=[],
                        )

                    axe_info.update_lumberjack_status(
                        lumberjack_name, lumberjack_idx, lumberjack_total
                    )
                    axe_dashboard.update_lumberjack_overview(
                        snapshot=jack_snap,
                        idx=lumberjack_idx,
                        total=lumberjack_total,
                        countdown=self._countdown_remaining,
                    )
                else:
                    # No selectable lumberjack — paint a quiet placeholder.
                    # The synthetic "axe" sidebar row is gone, so this branch
                    # only fires when zero lumberjacks are configured.
                    axe_info.update_status(self.axe_running)
                    from ...keymaps import key_display_name

                    axe_dashboard.update_empty_axe_display(
                        is_running=self.axe_running,
                        countdown=self._countdown_remaining,
                        add_key=key_display_name(
                            self._keymap_registry.app.add_axe_item
                        ),
                        degraded_status=self._axe_degraded_status,
                    )
            else:
                # Showing a bgcmd view — paint from cache when available. On a
                # cold miss we fall back to the cached slot list (no I/O) so
                # the header still renders; the Logs tab shows an empty string
                # until the async collector lands.
                slot = self._axe_current_view
                bg_snap = self._axe_bgcmd_details.get(slot)
                if bg_snap is not None:
                    info = bg_snap.info
                    running = bg_snap.running
                    output = bg_snap.output_tail
                else:
                    info = dict(self._bgcmd_slots).get(slot)
                    running = info is not None and info.running
                    output = ""

                axe_info.update_bgcmd_status(slot, info, running)
                axe_dashboard.update_bgcmd_display(
                    info, output, running, self._countdown_remaining
                )

            from ...modals import get_runner_count

            footer.set_axe_running(self.axe_running)
            running_count, done_count = self._get_bgcmd_counts()
            footer.set_bgcmd_count(running_count, done_count)
            self._push_service_health(footer)
            footer.set_runner_count(get_runner_count())
            if getattr(self, "_leader_mode_active", False):
                footer.update_leader_bindings(current_tab="services")
            elif getattr(self, "_bang_mode_active", False):
                footer.update_bang_bindings()
            elif getattr(self, "_copy_mode_active", False):
                footer.update_copy_bindings(
                    self.current_tab,
                    artifacts_pane_key=getattr(
                        self, "current_artifacts_pane_key", None
                    ),
                )
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
                            sel_info = dict(self._bgcmd_slots).get(sel_item.slot)
                            selected_slot_done = (
                                sel_info is None or not sel_info.running
                            )
                chop_run_total = 0
                chop_selected = self._axe_chop_selection is not None
                service_selected = self._axe_service_selection is not None
                service_running = False
                service_enabled = True
                service_available = True
                if self._axe_service_selection is not None and self._service_status:
                    proc = next(
                        (
                            item
                            for item in self._service_status.procs
                            if item.name == self._axe_service_selection
                        ),
                        None,
                    )
                    if proc is not None:
                        service_running = proc.state == "running"
                        service_enabled = proc.enablement.enabled
                        service_available = proc.available
                chop_selected_running = False
                chop_selected_enabled = True
                if self._axe_chop_selection is not None:
                    chop_snap = self._axe_chop_snapshots.get(self._axe_chop_selection)
                    if chop_snap is not None:
                        chop_selected_enabled = chop_snap.enabled
                        chop_run_total = len(chop_snap.runs)
                        if chop_snap.runs:
                            chop_selected_running = chop_snap.runs[0].entry.status in {
                                "running",
                                "launched",
                            }
                footer.update_axe_bindings(
                    axe_current_view=self._axe_current_view,
                    selected_slot_done=selected_slot_done,
                    chop_run_total=chop_run_total,
                    chop_selected=chop_selected,
                    chop_selected_running=chop_selected_running,
                    chop_selected_enabled=chop_selected_enabled,
                    service_selected=service_selected,
                    service_running=service_running,
                    service_enabled=service_enabled,
                    service_available=service_available,
                    config_row_selected=(
                        0 <= self.current_idx < len(self._axe_items)
                        and isinstance(
                            self._axe_items[self.current_idx],
                            (LumberjackItem, ChopItem),
                        )
                    ),
                    description_expanded=self.axe_description_expanded,  # type: ignore[attr-defined]
                )

            # Always update the side-panel list. Pass cached statuses and
            # running flags so the side-panel render path does no disk I/O.
            try:
                bgcmd_list = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
                bgcmd_running_cache = {
                    slot: snap.running for slot, snap in self._axe_bgcmd_details.items()
                }
                lumberjack_overruns = {
                    name: snap.overrun_chop_count
                    for name, snap in self._axe_lumberjack_snapshots.items()
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
                    chop_snapshots=self._axe_chop_snapshots,
                    lumberjack_overruns=lumberjack_overruns,
                    service_procs=(
                        {proc.name: proc for proc in self._service_status.procs}
                        if self._service_status is not None
                        else None
                    ),
                )
            except Exception:
                pass

            # Keep following live output, but leave terminal chop runs at the
            # RESULT card instead of immediately scrolling it off screen.
            selected_chop_active = True
            if self._axe_chop_selection is not None:
                chop_snap = self._axe_chop_snapshots.get(self._axe_chop_selection)
                run_idx = self._axe_resolve_chop_run_offset(self._axe_chop_selection)
                selected_chop_active = _chop_allows_auto_scroll(chop_snap, run_idx)
            if (
                self._axe_pinned_to_bottom
                and self._axe_current_view == "axe"
                and selected_chop_active
            ):
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
            service_snapshot = getattr(self, "_service_status", None)
            axe_info.update_host_chrome(
                None if service_snapshot is None else service_snapshot.host,
            )
            if self._axe_current_view == "axe":
                service_selection = self._axe_service_selection
                chop_selection = self._axe_chop_selection
                if service_selection is not None:
                    service_snapshot = self._service_status
                    procs = () if service_snapshot is None else service_snapshot.procs
                    proc = next(
                        (item for item in procs if item.name == service_selection),
                        None,
                    )
                    service_idx = next(
                        (
                            idx
                            for idx, item in enumerate(procs)
                            if item.name == service_selection
                        ),
                        0,
                    )
                    axe_info.update_service_status(
                        name=service_selection,
                        idx=service_idx,
                        total=len(procs),
                        proc=proc,
                    )
                elif chop_selection is not None:
                    lj_name, chop_name = chop_selection
                    chop_snap = self._axe_chop_snapshots.get(chop_selection)
                    run_total = len(chop_snap.runs) if chop_snap is not None else 0
                    run_idx = self._axe_resolve_chop_run_offset(chop_selection)
                    axe_info.update_chop_status(
                        lumberjack_name=lj_name,
                        chop_name=chop_name,
                        run_idx=run_idx,
                        run_total=run_total,
                    )
                elif (
                    self._axe_lumberjack_idx is not None and self._axe_lumberjack_names
                ):
                    name = self._axe_lumberjack_names[self._axe_lumberjack_idx]
                    axe_info.update_lumberjack_status(
                        name, self._axe_lumberjack_idx, len(self._axe_lumberjack_names)
                    )
                else:
                    axe_info.update_status(self.axe_running)
            else:
                slot = self._axe_current_view
                snapshot = self._axe_bgcmd_details.get(slot)
                if snapshot is not None:
                    info = snapshot.info
                    running = snapshot.running
                else:
                    info = dict(self._bgcmd_slots).get(slot)
                    running = info is not None and info.running
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
            self._push_service_health(footer)
        except Exception:
            pass

    def _push_service_health(self, footer: Any) -> None:
        """Push the cached service-health roll-up to the footer pill.

        A toast fires only when health flips or the snapshot ``change_token``
        moves while unhealthy -- never on countdown ticks.
        """
        from ..._service_health import derive_service_health

        snapshot = getattr(self, "_service_status", None)
        health = derive_service_health(snapshot)
        footer.set_service_health(health)
        token = None if snapshot is None else snapshot.change_token
        signature = (health.healthy, health.summary, None if health.healthy else token)
        if signature == getattr(self, "_service_health_notified", None):
            return
        previous = getattr(self, "_service_health_notified", None)
        self._service_health_notified = signature
        if not health.healthy and (previous is None or previous[2] != token):
            try:
                self.notify(  # type: ignore[attr-defined]
                    f"Services unhealthy: {health.summary}", severity="warning"
                )
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

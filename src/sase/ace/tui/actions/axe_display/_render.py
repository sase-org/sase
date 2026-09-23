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
    from ._panels import ServicesPanelKey


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
        # Derive the selection so the info panel counter is accurate even
        # before the debounce fires.
        self._derive_axe_view_from_selection()

        try:
            self._refresh_axe_panel_highlights()
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
                status_error=getattr(self, "_service_status_error", None),
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

            # Always repaint the side panels. Pass cached statuses and
            # running flags so the side-panel render path does no disk I/O.
            try:
                self._paint_axe_panels()
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

    def _axe_panel_widgets(self) -> dict[str, Any] | None:
        """Return the mounted Services panels keyed by panel key, if any."""
        from ...widgets import BgCmdList

        try:
            procs_panel = self.query_one("#service-procs-panel", BgCmdList)  # type: ignore[attr-defined]
            routines_panel = self.query_one("#scheduled-routines-panel", BgCmdList)  # type: ignore[attr-defined]
        except Exception:
            return None
        return {"service_procs": procs_panel, "scheduled_routines": routines_panel}

    def _axe_focused_panel_key(self) -> ServicesPanelKey:
        """Return the panel holding the selection (derived, never stored)."""
        if 0 <= self.current_idx < len(self._axe_items):
            return self._axe_panel_index.panel_for_global(self.current_idx)
        return "service_procs"

    def _build_axe_panel_titles(self, focused_key: str) -> dict[str, Any]:
        """Build both panel border titles from the in-memory caches."""
        from ._panel_titles import (
            ScheduledRoutinesPanelStats,
            ServiceProcsPanelStats,
            scheduled_routines_panel_stats,
            scheduled_routines_panel_title,
            service_procs_panel_stats,
            service_procs_panel_title,
        )

        service_snapshot = getattr(self, "_service_status", None)
        service_procs = (
            None
            if service_snapshot is None
            else {proc.name: proc for proc in service_snapshot.procs}
        )
        bgcmd_infos = dict(self._bgcmd_slots)
        bgcmd_running_cache = {
            slot: snap.running for slot, snap in self._axe_bgcmd_details.items()
        }
        visible_oneshots: list[tuple[Any, bool]] = []
        if not self._axe_cmds_hidden:
            for slot, _ in sorted(self._bgcmd_slots, key=lambda x: x[0]):
                info = bgcmd_infos.get(slot)
                running = bgcmd_running_cache.get(
                    slot, info is not None and info.running
                )
                visible_oneshots.append((info, running))
        host_state = None if service_snapshot is None else service_snapshot.host.state
        procs_stats: ServiceProcsPanelStats = service_procs_panel_stats(
            procs=None if service_snapshot is None else service_snapshot.procs,
            oneshots=visible_oneshots,
            hidden_oneshots=len(self._bgcmd_slots) if self._axe_cmds_hidden else 0,
            host_state=host_state,
            status_unavailable=service_snapshot is None,
        )
        routines_stats: ScheduledRoutinesPanelStats = scheduled_routines_panel_stats(
            routine_names=list(self._axe_lumberjack_names),
            statuses=self._axe_lumberjack_statuses,
            chop_names=self._axe_lumberjack_chop_names,
            chop_snapshots=self._axe_chop_snapshots,
            overrun_counts={
                name: snap.overrun_chop_count
                for name, snap in self._axe_lumberjack_snapshots.items()
            },
            service_procs=service_procs,
        )
        return {
            "service_procs": service_procs_panel_title(
                procs_stats, focused=focused_key == "service_procs"
            ),
            "scheduled_routines": scheduled_routines_panel_title(
                routines_stats, focused=focused_key == "scheduled_routines"
            ),
        }

    def _service_procs_empty_placeholder(self) -> Any:
        """Return the disabled placeholder for an empty Service Procs panel."""
        from rich.text import Text

        return Text("No service procs", style="dim")

    def _routines_empty_placeholder(self) -> Any:
        """Return the disabled placeholder for an empty Routines panel."""
        from rich.text import Text

        from ...keymaps import key_display_name

        add_key = key_display_name(self._keymap_registry.app.add_axe_item)
        return Text(f"No routines configured · {add_key} to add", style="dim")

    def _paint_axe_panels(self) -> None:
        """Repaint both Services panels from the cached state (no disk I/O)."""
        widgets = self._axe_panel_widgets()
        if widgets is None:
            return
        from ._panels import SERVICES_PANEL_ORDER

        focused_key = self._axe_focused_panel_key()
        jump_hints: dict[int, str] | None = (
            self._entry_jump_index_to_hint if self._entry_jump_mode_active else None
        )
        bgcmd_running_cache = {
            slot: snap.running for slot, snap in self._axe_bgcmd_details.items()
        }
        lumberjack_overruns = {
            name: snap.overrun_chop_count
            for name, snap in self._axe_lumberjack_snapshots.items()
        }
        service_snapshot = getattr(self, "_service_status", None)
        service_procs = (
            None
            if service_snapshot is None
            else {proc.name: proc for proc in service_snapshot.procs}
        )
        titles = self._build_axe_panel_titles(focused_key)
        placeholders = {
            "service_procs": self._service_procs_empty_placeholder(),
            "scheduled_routines": self._routines_empty_placeholder(),
        }
        for key in SERVICES_PANEL_ORDER:
            widget = widgets[key]
            panel_slice = self._axe_panel_index.slice_for(key)
            local_idx = self._axe_panel_index.local_idx_for(key, self.current_idx)
            local_hints: dict[int, str] | None = None
            if jump_hints:
                mapped = {}
                for global_idx, hint in jump_hints.items():
                    local = self._axe_panel_index.local_idx_for(key, global_idx)
                    if local >= 0:
                        mapped[local] = hint
                local_hints = mapped or None
            widget.update_list(
                items=list(panel_slice.items),
                current_idx=local_idx,
                axe_running=self.axe_running,
                lumberjack_names=self._axe_lumberjack_names,
                bgcmd_infos=dict(self._bgcmd_slots),
                jump_hints=local_hints,
                lumberjack_statuses=self._axe_lumberjack_statuses,
                bgcmd_running=bgcmd_running_cache,
                chop_snapshots=self._axe_chop_snapshots,
                lumberjack_overruns=lumberjack_overruns,
                service_procs=service_procs,
                empty_placeholder=placeholders[key],
            )
            widget.update_border_title(titles[key])
            if key == focused_key:
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")
        self._axe_painted_panel_key = focused_key
        self._apply_axe_panel_heights(widgets)
        self._settle_axe_sidebar_width(widgets)

    def _refresh_axe_panel_highlights(self) -> None:
        """Update panel highlights for j/k without rebuilding options.

        Same-panel moves touch one widget (the hot path stays O(1)
        widget work); focus crossings swap the highlight, the focus
        chrome, and both titles, then move Textual focus.
        """
        from ._panels import SERVICES_PANEL_ORDER

        widgets = self._axe_panel_widgets()
        if widgets is None:
            return
        focused_key = self._axe_focused_panel_key()
        local_idx = self._axe_panel_index.local_idx_for(focused_key, self.current_idx)
        painted_key = getattr(self, "_axe_painted_panel_key", focused_key)
        if painted_key == focused_key:
            widgets[focused_key].update_highlight(local_idx)
            return
        for key in SERVICES_PANEL_ORDER:
            widget = widgets[key]
            if key == focused_key:
                widget.update_highlight(local_idx)
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")
                widget.clear_highlight()
        titles = self._build_axe_panel_titles(focused_key)
        for key in SERVICES_PANEL_ORDER:
            widgets[key].update_border_title(titles[key])
        self._axe_painted_panel_key = focused_key
        self._focus_axe_focused_panel()

    def _focus_axe_focused_panel(self, *, force: bool = False) -> None:
        """Set Textual focus on the focused-panel ``BgCmdList``.

        Focus moves only when a ``BgCmdList`` already owns app focus and
        the hint input bar is not active, so background refreshes never
        steal focus from the prompt bar or a modal. ``force=True`` skips
        the ownership check (startup and prompt-bar remount paths).
        """
        from ...widgets import BgCmdList

        widgets = self._axe_panel_widgets()
        if widgets is None:
            return
        if not force:
            hint_bar_active = getattr(self, "_hint_input_bar_active", None)
            if callable(hint_bar_active) and hint_bar_active():
                return
            try:
                owned = isinstance(self.focused, BgCmdList)  # type: ignore[attr-defined]
            except Exception:
                return
            if not owned:
                return
        try:
            widgets[self._axe_focused_panel_key()].focus()
        except Exception:
            pass

    def _apply_axe_panel_heights(self, widgets: dict[str, Any]) -> None:
        """Size the two Services panels from their rendered line counts."""
        from textual.css.query import NoMatches

        from ...util.panel_heights import allocate_panel_heights

        try:
            container = self.query_one("#bgcmd-list-container")  # type: ignore[attr-defined]
        except (NoMatches, Exception):
            return
        size = getattr(container, "size", None)
        container_height = getattr(size, "height", 0) if size is not None else 0
        if not container_height:
            try:
                self.call_after_refresh(self._reapply_axe_panel_heights)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        from ._panels import SERVICES_PANEL_ORDER

        ordered = [widgets[key] for key in SERVICES_PANEL_ORDER]
        heights = allocate_panel_heights(
            [int(getattr(w, "rendered_line_count", 0)) for w in ordered],
            [False, False],
            container_height,
            filler_idx=1,
        )
        if heights is None:
            return
        for widget, height in zip(ordered, heights, strict=True):
            widget.styles.height = height.to_scalar()

    def _reapply_axe_panel_heights(self) -> None:
        """Re-run the Services height computation without rebuilding options."""
        widgets = self._axe_panel_widgets()
        if widgets is None:
            return
        try:
            container = self.query_one("#bgcmd-list-container")  # type: ignore[attr-defined]
        except Exception:
            return
        size = getattr(container, "size", None)
        if not (getattr(size, "height", 0) if size is not None else 0):
            return
        self._apply_axe_panel_heights(widgets)

    def _settle_axe_sidebar_width(self, widgets: dict[str, Any]) -> None:
        """Size the sidebar to the painted panels, in the same frame."""
        from ..._app_layout import services_sidebar_width

        from ._panels import SERVICES_PANEL_ORDER

        ordered = [widgets[key] for key in SERVICES_PANEL_ORDER]
        requested = [int(getattr(w, "_requested_width", 0)) for w in ordered]
        if not any(width > 0 for width in requested):
            return
        try:
            container = self.query_one("#bgcmd-list-container")  # type: ignore[attr-defined]
        except Exception:
            return
        terminal_width = getattr(getattr(self, "size", None), "width", 0) or 0
        container.styles.width = services_sidebar_width(
            requested, terminal_width=terminal_width
        )

    def _update_axe_info_panel(self) -> None:
        """Update the axe info panel and dashboard status bar with countdown."""
        from ...widgets import AxeDashboard, AxeInfoPanel

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            service_snapshot = getattr(self, "_service_status", None)
            axe_info.update_host_chrome(
                None if service_snapshot is None else service_snapshot.host,
                status_error=getattr(self, "_service_status_error", None),
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

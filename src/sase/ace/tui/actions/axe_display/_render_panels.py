"""Side-panel painting mixin for the ace axe display.

Repaints the Services-tab side panels (service procs plus the User,
Plugin, and Builtin routine sections), their border titles, highlights,
and layout from the in-memory caches populated by
``AxeDisplayLoadersMixin``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._loaders import AxeDisplayLoadersMixin

if TYPE_CHECKING:
    from ...keymaps import KeymapRegistry
    from ._panels import ServicesPanelKey


class AxeDisplayPanelsMixin(AxeDisplayLoadersMixin):
    """Mixin providing the axe side-panel painting and layout methods."""

    _keymap_registry: KeymapRegistry

    def _axe_panel_widgets(self) -> dict[str, Any] | None:
        """Return the mounted Services panels keyed by panel key, if any."""
        from ...widgets import BgCmdList

        try:
            procs_panel = self.query_one("#service-procs-panel", BgCmdList)  # type: ignore[attr-defined]
            user_panel = self.query_one("#user-routines-panel", BgCmdList)  # type: ignore[attr-defined]
            plugin_panel = self.query_one("#plugin-routines-panel", BgCmdList)  # type: ignore[attr-defined]
            builtin_panel = self.query_one("#builtin-routines-panel", BgCmdList)  # type: ignore[attr-defined]
        except Exception:
            return None
        return {
            "service_procs": procs_panel,
            "user_routines": user_panel,
            "plugin_routines": plugin_panel,
            "builtin_routines": builtin_panel,
        }

    def _axe_focused_panel_key(self) -> ServicesPanelKey:
        """Return the panel holding the selection (derived, never stored)."""
        if 0 <= self.current_idx < len(self._axe_items):
            return self._axe_panel_index.panel_for_global(self.current_idx)
        return "service_procs"

    def _routine_names_for_panel(self, panel_key: str) -> list[str]:
        """Return cached routine names belonging to ``panel_key``."""
        from ._panels import ROUTINE_PANEL_ORDER, routine_panel_key_for_source

        origins = getattr(self, "_axe_routine_origins", None) or {}
        names: list[str] = []
        for name in self._axe_lumberjack_names:
            origin = origins.get(name)
            source = getattr(origin, "source", origin) if origin is not None else "user"
            if isinstance(origin, dict):
                candidate = origin.get("source", source)
                if isinstance(candidate, str):
                    source = candidate
            if source not in ("user", "plugin", "builtin"):
                # Missing origins fall back to User; unknown strings fail
                # at index build time, so treat missing as User here too.
                if origin is None:
                    source = "user"
                else:
                    continue
            try:
                if routine_panel_key_for_source(source) == panel_key:  # type: ignore[arg-type]
                    names.append(name)
            except ValueError:
                continue
        return sorted(names)

    def _build_axe_panel_titles(self, focused_key: str) -> dict[str, Any]:
        """Build all panel border titles from the in-memory caches."""
        from ._panel_titles import (
            ROUTINE_PANEL_LABELS,
            ScheduledRoutinesPanelStats,
            ServiceProcsPanelStats,
            scheduled_routines_panel_stats,
            service_procs_panel_stats,
            service_procs_panel_title,
            source_routine_panel_title,
        )
        from ._panels import ROUTINE_PANEL_ORDER

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
        titles: dict[str, Any] = {
            "service_procs": service_procs_panel_title(
                procs_stats, focused=focused_key == "service_procs"
            ),
        }
        # Scheduler badge renders once, on the first visible routine panel.
        first_routine_panel = self._axe_panel_index.first_visible_routine_panel()
        overrun_counts = {
            name: snap.overrun_chop_count
            for name, snap in self._axe_lumberjack_snapshots.items()
        }
        for key in ROUTINE_PANEL_ORDER:
            routine_names = self._routine_names_for_panel(key)
            routines_stats: ScheduledRoutinesPanelStats = (
                scheduled_routines_panel_stats(
                    routine_names=routine_names,
                    statuses=self._axe_lumberjack_statuses,
                    chop_names=self._axe_lumberjack_chop_names,
                    chop_snapshots=self._axe_chop_snapshots,
                    overrun_counts=overrun_counts,
                    service_procs=service_procs if key == first_routine_panel else None,
                )
            )
            titles[key] = source_routine_panel_title(
                routines_stats,
                focused=focused_key == key,
                label=ROUTINE_PANEL_LABELS[key],
            )
        return titles

    def _service_procs_empty_placeholder(self) -> Any:
        """Return the disabled placeholder for an empty Service Procs panel."""
        from rich.text import Text

        return Text("No service procs", style="dim")

    def _routines_empty_placeholder(self) -> Any:
        """Return the disabled placeholder for the empty User Routines panel."""
        from rich.text import Text

        from ...keymaps import key_display_name

        add_key = key_display_name(self._keymap_registry.app.add_axe_item)
        return Text(f"No routines configured · {add_key} to add", style="dim")

    def _paint_axe_panels(self) -> None:
        """Repaint visible Services panels from the cached state (no disk I/O)."""
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
        from ._panel_titles import routine_health_count

        lumberjack_health = {
            name: routine_health_count(
                name, self._axe_lumberjack_chop_names, self._axe_chop_snapshots
            )
            for name in self._axe_lumberjack_names
        }
        service_snapshot = getattr(self, "_service_status", None)
        service_procs = (
            None
            if service_snapshot is None
            else {proc.name: proc for proc in service_snapshot.procs}
        )
        titles = self._build_axe_panel_titles(focused_key)
        visible_keys = self._axe_panel_index.visible_keys()
        for key in SERVICES_PANEL_ORDER:
            widget = widgets[key]
            if key not in visible_keys:
                try:
                    widget.display = False
                except Exception:
                    pass
                continue
            try:
                widget.display = True
            except Exception:
                pass
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
            empty_placeholder = None
            if key == "service_procs":
                empty_placeholder = self._service_procs_empty_placeholder()
            elif key == "user_routines":
                empty_placeholder = self._routines_empty_placeholder()
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
                lumberjack_health=lumberjack_health,
                service_procs=service_procs,
                empty_placeholder=empty_placeholder,
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
        chrome, and visible titles, then move Textual focus.
        """
        from ._panels import SERVICES_PANEL_ORDER

        widgets = self._axe_panel_widgets()
        if widgets is None:
            return
        focused_key = self._axe_focused_panel_key()
        local_idx = self._axe_panel_index.local_idx_for(focused_key, self.current_idx)
        painted_key = getattr(self, "_axe_painted_panel_key", focused_key)
        visible_keys = self._axe_panel_index.visible_keys()
        if painted_key == focused_key:
            widgets[focused_key].update_highlight(local_idx)
            return
        for key in SERVICES_PANEL_ORDER:
            if key not in visible_keys:
                continue
            widget = widgets[key]
            if key == focused_key:
                widget.update_highlight(local_idx)
                widget.add_class("-focused-panel")
            else:
                widget.remove_class("-focused-panel")
                widget.clear_highlight()
        titles = self._build_axe_panel_titles(focused_key)
        for key in visible_keys:
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
        """Size the visible Services panels from their rendered line counts."""
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
        visible_keys = self._axe_panel_index.visible_keys()
        ordered = [widgets[key] for key in visible_keys]
        heights = allocate_panel_heights(
            [int(getattr(w, "rendered_line_count", 0)) for w in ordered],
            [False for _ in ordered],
            container_height,
            filler_idx=len(ordered) - 1,
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
        """Size the sidebar to the visible panels, in the same frame."""
        from ..._app_layout import services_sidebar_width

        visible_keys = self._axe_panel_index.visible_keys()
        ordered = [widgets[key] for key in visible_keys]
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

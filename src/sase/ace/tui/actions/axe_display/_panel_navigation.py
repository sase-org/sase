"""Services-panel focus navigation actions for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._data import TabName


class AxePanelNavigationMixin:
    """Mixin providing J/K jumps between Services-tab side panels."""

    current_tab: TabName
    current_idx: int
    _axe_items: list[Any]

    def _change_focused_service_panel(self, *, forward: bool) -> None:
        """Select the first/last nav item of the adjacent non-empty panel.

        ``J`` (forward) lands on the first nav item of the next panel;
        ``K`` (backward) lands on the last rendered nav item of the previous
        panel, both with wrap. No-op off the Services tab or when no
        other panel has nav items.
        """
        if self.current_tab != "services":
            return
        from ._panels import SERVICES_PANEL_ORDER

        panel_index = getattr(self, "_axe_panel_index", None)
        if panel_index is None:
            return
        current_key = panel_index.panel_for_global(self.current_idx)
        if current_key not in SERVICES_PANEL_ORDER:
            current_key = "service_procs"
        target_key = panel_index.adjacent_nonempty_panel(current_key, forward=forward)
        if target_key is None:
            return
        target_idx = (
            panel_index.first_global(target_key)
            if forward
            else panel_index.last_global(target_key)
        )
        if target_idx is None or target_idx == self.current_idx:
            return
        push_origin = getattr(self, "_push_entry_jump_index_origin_if_changed", None)
        if callable(push_origin):
            push_origin(target_idx=target_idx)
        self.current_idx = target_idx

    def action_focus_next_service_panel(self) -> None:
        """Move focus to the first node of the next Services panel."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin("next_service_panel")
        record_navigation = getattr(self, "_record_jk_navigation", None)
        if callable(record_navigation):
            record_navigation()
        self._change_focused_service_panel(forward=True)
        jk_perf = getattr(self, "_jk_perf", None)
        if jk_perf is not None:
            self.call_after_refresh(jk_perf.mark_painted)  # type: ignore[attr-defined]

    def action_focus_prev_service_panel(self) -> None:
        """Move focus to the last node of the previous Services panel."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin("prev_service_panel")
        record_navigation = getattr(self, "_record_jk_navigation", None)
        if callable(record_navigation):
            record_navigation()
        self._change_focused_service_panel(forward=False)
        jk_perf = getattr(self, "_jk_perf", None)
        if jk_perf is not None:
            self.call_after_refresh(jk_perf.mark_painted)  # type: ignore[attr-defined]

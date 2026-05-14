"""Tag-panel focus navigation actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._navigation_order import rendered_panel_slice
from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import AgentPanelGroup


class AgentPanelNavigationMixin:
    """Mixin providing navigation between tag-driven agent side panels."""

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _panel_group: AgentPanelGroup
    _current_group_key: tuple[str, ...] | None
    _agent_panels_grouped: bool
    _agents: list[Agent]

    def _first_agent_idx_for_focused_group(
        self, group_key: tuple[str, ...]
    ) -> int | None:
        """Return the first global agent index covered by a focused-panel group."""
        from ...models.agent_groups import GroupingMode, build_agent_tree

        focused_key = self._panel_group.focused_key
        global_indices, panel_agents = rendered_panel_slice(self, focused_key)
        tree = build_agent_tree(
            panel_agents,
            fold_registry=getattr(self, "_group_fold_registry", None),
            mode=getattr(self, "_grouping_mode", GroupingMode.STANDARD),
        )
        for entry in tree:
            if entry.kind != "group" or entry.group is None:
                continue
            if entry.group.group_key != group_key:
                continue
            for local_idx in entry.group.agent_indices:
                if 0 <= local_idx < len(global_indices):
                    return global_indices[local_idx]
            return None
        return None

    def _focus_panel_navigation_stop(
        self, stop: tuple[str, int | tuple[str, ...]]
    ) -> None:
        """Move focus to a selectable row in the current panel."""
        kind, payload = stop
        if kind == "banner":
            assert isinstance(payload, tuple)
            self._current_group_key = payload  # type: ignore[attr-defined]
            anchor_idx = self._first_agent_idx_for_focused_group(payload)
            if anchor_idx is not None:
                self.current_idx = anchor_idx  # type: ignore[attr-defined]
            return

        assert isinstance(payload, int)
        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_idx = payload  # type: ignore[attr-defined]

    def _change_focused_agent_panel(self, *, forward: bool) -> None:
        """Cycle focus between tag-driven side panels with wrap.

        Next-panel focus lands on the first selectable row in the new
        panel's rendered order; previous-panel focus lands on the last.
        No-ops when only one panel exists.
        """
        if self.current_tab != "agents":
            return
        if self._guard_agent_navigation_for_artifact_viewer():  # type: ignore[attr-defined]
            return
        old_focused_idx = self._panel_group.focused_idx
        if forward:
            changed = self._panel_group.focus_next()
        else:
            changed = self._panel_group.focus_prev()
        if not changed:
            return

        self.current_attempt_number = None  # type: ignore[attr-defined]
        stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        if stops:
            self._focus_panel_navigation_stop(stops[0] if forward else stops[-1])
        else:
            self._current_group_key = None  # type: ignore[attr-defined]
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                keys_per_agent,
                self._panel_group.focused_key,
            )
        refresh_focused_panel = getattr(self, "_refresh_focused_agent_panel", None)
        if callable(refresh_focused_panel):
            refresh_focused_panel(old_focused_idx=old_focused_idx)
        else:
            self._refresh_agents_display(list_changed=False)  # type: ignore[attr-defined]

        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
        apply_immediate = getattr(self, "_apply_agent_detail_immediate", None)
        if callable(apply_immediate):
            apply_immediate()
        debouncer = getattr(self, "_agent_detail_debouncer", None)
        fire_detail = getattr(self, "_fire_debounced_detail_update", None)
        if debouncer is not None and callable(fire_detail):
            debouncer.schedule(fire_detail)

    def action_focus_next_agent_panel(self) -> None:
        """Move focus to the next tag-driven side panel (with wrap)."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin("next_agent_panel")
        record_navigation = getattr(self, "_record_jk_navigation", None)
        if callable(record_navigation):
            record_navigation()
        self._change_focused_agent_panel(forward=True)
        jk_perf = getattr(self, "_jk_perf", None)
        if jk_perf is not None:
            self.call_after_refresh(jk_perf.mark_painted)  # type: ignore[attr-defined]

    def action_focus_prev_agent_panel(self) -> None:
        """Move focus to the previous tag-driven side panel (with wrap)."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin("prev_agent_panel")
        record_navigation = getattr(self, "_record_jk_navigation", None)
        if callable(record_navigation):
            record_navigation()
        self._change_focused_agent_panel(forward=False)
        jk_perf = getattr(self, "_jk_perf", None)
        if jk_perf is not None:
            self.call_after_refresh(jk_perf.mark_painted)  # type: ignore[attr-defined]

    def action_toggle_agent_panel_grouping(self) -> None:
        """Toggle Agents tab panels between tag-split and merged layouts."""
        if self.current_tab != "agents":
            return
        self._agent_panels_grouped = not getattr(self, "_agent_panels_grouped", False)
        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_attempt_number = None  # type: ignore[attr-defined]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        label = "grouped" if self._agent_panels_grouped else "split"
        self.notify(f"Agent panels: {label}", timeout=1.5)  # type: ignore[attr-defined]

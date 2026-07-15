"""Tag-panel focus navigation actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._fold_scope import focused_panel_fold_registry
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
            fold_registry=focused_panel_fold_registry(self),
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
        if len(self._panel_group.panel_keys) <= 1:
            return
        old_focused_idx = self._panel_group.focused_idx
        old_idx = self.current_idx
        old_group_key = self._current_group_key
        old_agent = (
            self._agents[old_idx]
            if old_group_key is None and 0 <= old_idx < len(self._agents)
            else None
        )
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()
        if forward:
            changed = self._panel_group.focus_next()
        else:
            changed = self._panel_group.focus_prev()
        if not changed:
            return

        self.current_attempt_number = None  # type: ignore[attr-defined]
        stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        destination: tuple[str, int | tuple[str, ...]] | None = None
        if stops:
            destination = stops[0] if forward else stops[-1]
            self._focus_panel_navigation_stop(destination)
        else:
            self._current_group_key = None  # type: ignore[attr-defined]
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                keys_per_agent,
                self._panel_group.focused_key,
            )
            if 0 <= self.current_idx < len(self._agents):
                destination = ("agent", self.current_idx)

        if old_agent is not None and destination != ("agent", old_idx):
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)

        if destination is not None:
            kind, payload = destination
            if kind == "agent":
                assert isinstance(payload, int)
                if 0 <= payload < len(self._agents):
                    ack_unread = getattr(self, "_acknowledge_agent_unread", None)
                    if callable(ack_unread):
                        ack_unread(self._agents[payload])

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
        collapsed_keys = getattr(self, "_collapsed_panel_keys", None)
        if collapsed_keys is not None:
            collapsed_keys.clear()
        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_attempt_number = None  # type: ignore[attr-defined]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        label = "grouped" if self._agent_panels_grouped else "split"
        self.notify(f"Agent panels: {label}", timeout=1.5)  # type: ignore[attr-defined]

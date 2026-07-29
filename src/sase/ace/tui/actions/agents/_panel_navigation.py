"""Tribe-panel focus navigation actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._fold_scope import focused_panel_fold_registry
from ._navigation_order import rendered_panel_slice
from ._panel_fold_intent import effective_panel_collapses
from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import AgentPanelGroup, PanelKey


class AgentPanelNavigationMixin:
    """Mixin providing navigation between tribe-driven agent side panels."""

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _panel_group: AgentPanelGroup
    _current_group_key: tuple[str, ...] | None
    _agent_panels_grouped: bool
    _agents: list[Agent]

    def _resolve_last_expanded_panel_target(
        self,
    ) -> tuple[int, PanelKey] | None:
        """Return the bottom-most live expanded split-panel target."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None or getattr(self, "_agent_panels_grouped", False):
            return None

        panel_keys = panel_group.panel_keys
        collapsed_keys = effective_panel_collapses(self, panel_keys)
        target: tuple[int, PanelKey] | None = None
        for panel_idx, panel_key in enumerate(panel_keys):
            if panel_key not in collapsed_keys:
                target = (panel_idx, panel_key)
        return target

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
            remember = getattr(self, "_remember_focused_panel_selection", None)
            if callable(remember):
                remember(stop)
            return

        assert isinstance(payload, int)
        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_idx = payload  # type: ignore[attr-defined]
        remember = getattr(self, "_remember_focused_panel_selection", None)
        if callable(remember):
            remember(stop)
        self._acknowledge_panel_stop_arrival(payload)

    def _acknowledge_panel_stop_arrival(self, agent_idx: int) -> None:
        """Clear unread state for the row a panel move just selected."""
        agents = getattr(self, "_agents", ())
        if not (0 <= agent_idx < len(agents)):
            return
        ack_unread = getattr(self, "_acknowledge_agent_unread", None)
        if callable(ack_unread):
            # Some callers also acknowledge fallback destinations; the
            # underlying unread transition is intentionally idempotent.
            ack_unread(agents[agent_idx])

    def _focus_whole_panel_target(
        self,
        target: tuple[int, PanelKey],
    ) -> bool:
        """Focus one stable panel target without descending into its rows."""
        panel_idx, panel_key = target
        panel_keys = self._panel_group.panel_keys
        if (
            not (0 <= panel_idx < len(panel_keys))
            or panel_keys[panel_idx] != panel_key
            or panel_idx == self._panel_group.focused_idx
        ):
            return False

        old_focused_idx = self._panel_group.focused_idx
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()

        self._panel_group.focused_idx = panel_idx
        self._expanded_panel_focus = True
        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_attempt_number = None  # type: ignore[attr-defined]

        remembered = getattr(self, "_panel_selection_memory", {}).get(panel_key)
        global_indices, _agents = rendered_panel_slice(self, panel_key)
        if (
            remembered is not None
            and remembered[0] == "agent"
            and isinstance(remembered[1], int)
            and remembered[1] in global_indices
        ):
            self.current_idx = remembered[1]
        elif global_indices:
            self.current_idx = global_indices[0]

        refresh = getattr(self, "_refresh_panel_focus_state", None)
        if callable(refresh):
            refresh(
                old_focused_idx=old_focused_idx,
                render_detail_immediate=False,
            )
        return True

    def _focus_last_expanded_panel(self) -> bool:
        """Select the bottom-most expanded panel, if one is currently live."""
        target = self._resolve_last_expanded_panel_target()
        return target is not None and self._focus_whole_panel_target(target)

    def _step_whole_panel_focus(self, *, forward: bool) -> bool:
        """Select the adjacent whole panel, wrapping over every panel key."""
        panel_keys = self._panel_group.panel_keys
        current_idx = self._panel_group.focused_idx
        target_idx = (
            (current_idx + 1) % len(panel_keys)
            if forward
            else (current_idx - 1) % len(panel_keys)
        )
        if not self._focus_whole_panel_target((target_idx, panel_keys[target_idx])):
            return False
        # Whole-panel focus is reactive state outside ``current_idx``. Its
        # remembered row may be the same across a hop, so the ordinary index
        # watcher is not a reliable paint-sample terminator for lower-case
        # j/k instrumentation.
        jk_perf = getattr(self, "_jk_perf", None)
        if jk_perf is not None:
            self.call_after_refresh(jk_perf.mark_painted)  # type: ignore[attr-defined]
        return True

    def _change_whole_panel_focus(self, *, forward: bool) -> bool:
        """Move selected-panel focus without descending into either panel."""
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        focus = resolve_panel() if callable(resolve_panel) else None
        if focus is None:
            return False
        if len(self._panel_group.panel_keys) <= 1:
            return True

        self._step_whole_panel_focus(forward=forward)
        return True

    def _escape_dead_end_panel_focus(self, *, forward: bool) -> bool:
        """Select the adjacent whole panel from a panel with nowhere left to move."""
        panel_group = getattr(self, "_panel_group", None)
        if (
            self.current_tab != "agents"
            or getattr(self, "_agent_panels_grouped", False)
            or panel_group is None
            or len(panel_group.panel_keys) <= 1
        ):
            return False

        self._remember_focused_panel_selection()  # type: ignore[attr-defined]
        departing_agent = (
            self._agents[self.current_idx]
            if self._current_group_key is None
            and 0 <= self.current_idx < len(self._agents)
            else None
        )
        if not self._step_whole_panel_focus(forward=forward):
            return False

        arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
        if callable(arm_manual):
            arm_manual(departing_agent)
        return True

    def _change_focused_agent_panel(self, *, forward: bool) -> None:
        """Cycle focus between tribe-driven side panels with wrap.

        Next-panel focus lands on the first selectable row in the new
        expanded panel's rendered order; previous-panel focus lands on the
        last. No-ops when no other expanded panel exists.
        """
        if self.current_tab != "agents":
            return
        if self._guard_agent_navigation_for_artifact_file_viewer():  # type: ignore[attr-defined]
            return
        panel_keys = self._panel_group.panel_keys
        if len(panel_keys) <= 1:
            return
        # ``J`` / ``K`` mean "enter the first / last row of an adjacent panel",
        # so a collapsed panel -- which renders no selectable rows -- is never
        # a destination. With no expanded sibling left the keymaps are a pure
        # no-op: lowercase j/k whole-panel cycling remains the way to reach
        # collapsed panels.
        collapsed_keys = effective_panel_collapses(self, panel_keys)
        focused_idx = self._panel_group.focused_idx
        if all(
            key in collapsed_keys
            for idx, key in enumerate(panel_keys)
            if idx != focused_idx
        ):
            return
        # Uppercase J/K retain their row-jump meaning even when the origin is
        # a selected panel, so clear explicit expanded focus before choosing
        # the destination row.
        if getattr(self, "_expanded_panel_focus", False):
            self._expanded_panel_focus = False
        old_focused_idx = focused_idx
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
            changed = self._panel_group.focus_next(skip=collapsed_keys)
        else:
            changed = self._panel_group.focus_prev(skip=collapsed_keys)
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

        refresh_detail = getattr(self, "_refresh_agent_focus_detail", None)
        if callable(refresh_detail):
            refresh_detail()
        else:
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
        """Move focus to the next tribe-driven side panel (with wrap)."""
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
        """Move focus to the previous tribe-driven side panel (with wrap)."""
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
        """Toggle Agents tab panels between tribe-split and merged layouts."""
        if self.current_tab != "agents":
            return
        if getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode(  # type: ignore[attr-defined]
                refresh_titles=False
            )
        disarm_isolation = getattr(self, "_disarm_panel_isolation_revert", None)
        if callable(disarm_isolation):
            # The following full list repaint removes markers and refreshes
            # the footer, so no transient-only repaint is needed here.
            disarm_isolation(refresh=False)
        self._agent_panels_grouped = not getattr(self, "_agent_panels_grouped", False)
        self._expanded_panel_focus = False
        from ._panel_fold_intent import clear_panel_fold_intents

        clear_panel_fold_intents(self)
        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_attempt_number = None  # type: ignore[attr-defined]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        if self._agent_panels_grouped:
            record_clear = getattr(self, "_record_agents_panel_folds_cleared", None)
            if callable(record_clear):
                record_clear()
        label = "grouped" if self._agent_panels_grouped else "split"
        self.notify(f"Agent panels: {label}", timeout=1.5)  # type: ignore[attr-defined]

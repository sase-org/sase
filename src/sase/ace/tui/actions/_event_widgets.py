"""Widget message handlers for the ACE TUI."""

from __future__ import annotations

from textual import events

from ..widgets import AgentList, BgCmdList, ChangeSpecList, TabBar
from ._event_base import EventHandlersBase


class EventWidgetHandlersMixin(EventHandlersBase):
    """Mixin providing list, tab, and resize message handlers."""

    _current_group_key: tuple[str, ...] | None

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Treat mouse focus on a collapsed AgentList as whole-panel focus."""
        if self.current_tab != "agents":
            return
        from ..widgets import AgentList

        widget = event.widget
        if not isinstance(widget, AgentList):
            return
        wid = widget.id
        try:
            if wid == "agent-list-panel":
                panel_idx = 0
            elif wid is not None and wid.startswith("agent-list-panel-"):
                panel_idx = int(wid.rsplit("-", 1)[-1])
            else:
                return
        except ValueError:
            return

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return
        panel_keys = panel_group.panel_keys
        if not (0 <= panel_idx < len(panel_keys)):
            return
        panel_key = panel_keys[panel_idx]
        if (
            panel_key not in getattr(self, "_collapsed_panel_keys", set())
            or panel_idx == panel_group.focused_idx
        ):
            return
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return
        cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member_jump):
            cancel_member_jump(refresh_footer=False)

        old_focused_idx = panel_group.focused_idx
        old_idx = self.current_idx
        old_group_key = self._current_group_key
        old_agent = (
            self._agents[old_idx]
            if old_group_key is None and 0 <= old_idx < len(self._agents)
            else None
        )
        panel_group.focused_idx = panel_idx
        self._current_group_key = None
        self.current_attempt_number = None  # type: ignore[attr-defined]
        slot = self._agent_panel_index().slice_for(panel_key)  # type: ignore[attr-defined]
        if slot.global_indices:
            self.current_idx = slot.global_indices[0]
        if old_agent is not None:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)
        refresh_panel = getattr(self, "_refresh_focused_agent_panel", None)
        if callable(refresh_panel):
            refresh_panel(old_focused_idx=old_focused_idx)
        refresh_detail = getattr(self, "_refresh_agent_focus_detail", None)
        if callable(refresh_detail):
            refresh_detail()

    def on_change_spec_list_selection_changed(
        self, event: ChangeSpecList.SelectionChanged
    ) -> None:
        """Handle selection change in the ChangeSpec list widget."""
        if self.current_tab == "changespecs" and 0 <= event.index < len(
            self.changespecs
        ):
            # Push to history when clicking on a different ChangeSpec
            if event.index != self.current_idx:
                self._push_changespec_to_history()  # type: ignore[attr-defined]
            self.current_idx = event.index

    def on_agent_list_selection_changed(
        self, event: AgentList.SelectionChanged
    ) -> None:
        """Handle selection change in the Agent list widget.

        Each AgentList instance is a tag-bucket panel; ``event.index`` is
        local to that panel, so we translate it back to a global agent
        index using the panel's filtered slice.
        """
        if self.current_tab != "agents":
            return

        from ..widgets import AgentList

        widget = event.control
        if not isinstance(widget, AgentList):
            return
        wid = widget.id
        panel_keys = self._panel_group.panel_keys  # type: ignore[attr-defined]
        # Map widget id back to panel index.
        try:
            if wid == "agent-list-panel":
                panel_idx = 0
            elif wid is not None and wid.startswith("agent-list-panel-"):
                panel_idx = int(wid.rsplit("-", 1)[-1])
            else:
                return
        except ValueError:
            return
        if not (0 <= panel_idx < len(panel_keys)):
            return
        panel_key = panel_keys[panel_idx]

        slot = self._agent_panel_index().slice_for(panel_key)  # type: ignore[attr-defined]
        global_indices = slot.global_indices
        panel_agents = slot.agents

        if event.group_key is not None:
            # Banner row click — anchor focus on the first agent in the
            # banner's group (already mapped to a local index when
            # AgentList resolved the row).
            if not (0 <= event.index < len(panel_agents)):
                return
            target_global = global_indices[event.index]
        else:
            if not (0 <= event.index < len(panel_agents)):
                return
            target_global = global_indices[event.index]

        if (
            panel_idx != self._panel_group.focused_idx  # type: ignore[attr-defined]
            or target_global != self.current_idx
            or event.group_key != getattr(self, "_current_group_key", None)
            or event.attempt_number != self.current_attempt_number
        ):
            cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
            if callable(cancel_member_jump):
                cancel_member_jump(refresh_footer=False)
            guard = getattr(
                self, "_guard_agent_navigation_for_artifact_file_viewer", None
            )
            if callable(guard) and guard():
                return

        # Switching panel via mouse click moves panel focus too.
        if panel_idx != self._panel_group.focused_idx:  # type: ignore[attr-defined]
            self._panel_group.focused_idx = panel_idx  # type: ignore[attr-defined]
        # A row click always descends from explicit whole-panel focus.
        self._expanded_panel_focus = False

        old_idx = self.current_idx
        old_group_key = getattr(self, "_current_group_key", None)
        if (
            old_group_key is None
            and 0 <= old_idx < len(self._agents)
            and (target_global != old_idx or event.group_key is not None)
        ):
            old_agent = self._agents[old_idx]
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)
            else:
                manual_ids = getattr(self, "_manual_unread_agent_ids", None)
                if manual_ids is not None:
                    manual_ids.discard(old_agent.identity)

        # Updating current_idx clears _current_attempt_number (setter
        # in AceApp). Set the attempt number after so attempt-child
        # selections land on the pinned view.
        if target_global == self.current_idx:
            self.current_attempt_number = event.attempt_number  # type: ignore[attr-defined]
        else:
            self.current_idx = target_global
            self.current_attempt_number = event.attempt_number  # type: ignore[attr-defined]
        # A banner row carries a ``group_key`` so banner-aware actions
        # can target the group; selecting an agent row clears it.
        self._current_group_key = event.group_key  # type: ignore[attr-defined]
        remember = getattr(self, "_remember_focused_panel_selection", None)
        if callable(remember):
            remember(
                ("banner", event.group_key)
                if event.group_key is not None
                else ("agent", target_global)
            )

        if event.group_key is None and 0 <= target_global < len(self._agents):
            target_agent = self._agents[target_global]
            ack_unread = getattr(self, "_acknowledge_agent_unread", None)
            if callable(ack_unread):
                ack_unread(target_agent)
                return
            manual_ids = getattr(self, "_manual_unread_agent_ids", None)
            if isinstance(manual_ids, set) and target_agent.identity in manual_ids:
                return
            unread_ids = getattr(self, "_unread_completed_agent_ids", None)
            if unread_ids is not None and target_agent.identity in unread_ids:
                unread_ids.discard(target_agent.identity)
                patched = False
                patch_row = getattr(self, "_try_patch_agent_row", None)
                if callable(patch_row):
                    patched = bool(patch_row(target_agent))
                if not patched:
                    refresh = getattr(self, "_refresh_agents_display", None)
                    if callable(refresh):
                        refresh(list_changed=True, defer_detail=True)

    def on_tab_bar_tab_clicked(self, event: TabBar.TabClicked) -> None:
        """Handle tab clicks from the tab bar."""
        if event.tab != self.current_tab:
            # Save current position before switching
            self._save_current_tab_position()  # type: ignore[attr-defined]
            # Set appropriate index for target tab
            if event.tab == "changespecs":
                self.current_idx = self._get_clamped_changespecs_idx()  # type: ignore[attr-defined]
            elif event.tab == "agents":
                self.current_idx = self._get_clamped_agents_idx()  # type: ignore[attr-defined]
            else:  # axe
                self.current_idx = self._get_clamped_axe_idx()  # type: ignore[attr-defined]
            self.current_tab = event.tab  # type: ignore[assignment]

    def on_change_spec_list_width_changed(
        self, event: ChangeSpecList.WidthChanged
    ) -> None:
        """Handle width change from the list widget."""
        from textual.css.query import NoMatches

        from ..app import _MAX_LIST_WIDTH, _MIN_LIST_WIDTH

        width = max(_MIN_LIST_WIDTH, min(_MAX_LIST_WIDTH, event.width))
        try:
            list_container = self.query_one("#list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return
        list_container.styles.width = width

    def on_agent_list_width_changed(self, event: AgentList.WidthChanged) -> None:
        """Handle width change from the agent list widget."""
        from textual.css.query import NoMatches

        from ..app import _MAX_AGENT_LIST_WIDTH, _MIN_AGENT_LIST_WIDTH

        try:
            agent_list_container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return
        agent_lists = self.query("#agent-list-container AgentList").results(  # type: ignore[attr-defined]
            AgentList
        )
        requested_widths = [
            width
            for widget in agent_lists
            if (width := getattr(widget, "_requested_width", 0)) > 0
        ]
        desired_width = max([event.width, *requested_widths])
        width = max(_MIN_AGENT_LIST_WIDTH, min(_MAX_AGENT_LIST_WIDTH, desired_width))
        agent_list_container.styles.width = width

    def on_resize(self, _event: events.Resize) -> None:
        """Re-apply per-panel heights when geometry changes.

        Layout cycling and terminal resizes change the agent-list
        container's available height; the panel-sizing decision is
        height-dependent, so recompute without rebuilding options.
        """
        if not hasattr(self, "_panel_group"):
            return
        reapply = getattr(self, "_reapply_panel_heights", None)
        if reapply is not None:
            reapply()

    def on_bg_cmd_list_selection_changed(
        self, event: BgCmdList.SelectionChanged
    ) -> None:
        """Handle selection change in the BgCmdList widget."""
        if self.current_tab == "axe":
            self.current_idx = event.index

    def on_bg_cmd_list_width_changed(self, event: BgCmdList.WidthChanged) -> None:
        """Resize the AXE sidebar to fit its widest formatted row."""
        from textual.css.query import NoMatches

        from ..app import (
            _BGCMD_LIST_RESERVED_FOR_DASHBOARD,
            _MAX_BGCMD_LIST_WIDTH,
            _MIN_BGCMD_LIST_WIDTH,
        )

        try:
            container = self.query_one("#bgcmd-list-container")  # type: ignore[attr-defined]
        except NoMatches:
            return
        terminal_width = getattr(getattr(self, "size", None), "width", 0) or 0
        max_for_terminal = _MAX_BGCMD_LIST_WIDTH
        if terminal_width > 0:
            # Leave at least ``_BGCMD_LIST_RESERVED_FOR_DASHBOARD`` cells for
            # the right-hand AXE dashboard so a wide sidebar can never push
            # the dashboard out of the viewport on tight terminals.
            terminal_cap = max(
                _MIN_BGCMD_LIST_WIDTH,
                terminal_width - _BGCMD_LIST_RESERVED_FOR_DASHBOARD,
            )
            max_for_terminal = min(_MAX_BGCMD_LIST_WIDTH, terminal_cap)
        width = max(_MIN_BGCMD_LIST_WIDTH, min(max_for_terminal, event.width))
        container.styles.width = width

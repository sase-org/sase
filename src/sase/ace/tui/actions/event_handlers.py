"""Event handler mixin for the ace TUI app."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from textual import events

from ..activity_log import ActivityEventType, ActivityLog
from ..widgets import (
    AgentList,
    BgCmdList,
    ChangeSpecList,
    InactiveIndicator,
    TabBar,
)

if TYPE_CHECKING:
    from textual.widgets import Input

    from ...changespec import ChangeSpec
    from ..models import Agent

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class EventHandlersMixin:
    """Mixin providing event handlers and timer callbacks."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    _countdown_remaining: int
    _fold_mode_active: bool
    _checkout_mode_active: bool
    _copy_mode_active: bool
    _agents: list[Agent]
    _changespecs_last_idx: int
    _agents_last_idx: int
    _ancestor_mode_active: bool
    _child_mode_active: bool
    _sibling_mode_active: bool
    _hint_mode_active: bool
    _accept_mode_active: bool
    _leader_mode_active: bool
    _bang_mode_active: bool
    _custom_mode_active: str | None
    _custom_mode_prefixes: dict[str, str]
    _inactive_seconds: int
    _last_activity_time: float
    _last_activity_flush: float
    _activity_log: ActivityLog

    def _refresh_current_tab(self) -> None:
        """Refresh the display for whichever tab is currently active.

        Use this instead of _refresh_display() when the caller may be on any tab
        (e.g. exiting bang/copy mode).
        """
        if self.current_tab == "changespecs":
            self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._refresh_agents_display()  # type: ignore[attr-defined]
        else:  # axe
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _on_auto_refresh(self) -> None:
        """Auto-refresh handler called by timer."""
        self._countdown_remaining = self.refresh_interval

        # Always poll axe status regardless of tab (for STARTING/STOPPING states)
        self._load_axe_status()  # type: ignore[attr-defined]

        # Poll agent completions for notifications (regardless of tab)
        self._poll_agent_completions()  # type: ignore[attr-defined]

        # Skip changespec refresh if user is in an input mode
        # (prompt bar or hint bar is active)
        if getattr(self, "_prompt_context", None) is not None:
            return
        if getattr(self, "_hint_mode_active", False):
            return
        if getattr(self, "_accept_mode_active", False):
            return

        # Always refresh agents to keep the tab bar count up to date
        self._load_agents()  # type: ignore[attr-defined]

        # Tab-specific refreshes
        if self.current_tab == "changespecs":
            self._reload_and_reposition()  # type: ignore[attr-defined]
        # No else needed - axe display already refreshed by _load_axe_status()

    def _on_countdown_tick(self) -> None:
        """Countdown tick handler called every second."""
        now_mono = time.monotonic()
        if now_mono - self._last_activity_flush >= 10:
            if hasattr(self, "_last_activity_time"):
                activity_wall = time.time() - (now_mono - self._last_activity_time)
                # Always write the keypress file — this is the true
                # last-interaction timestamp that is_idle() uses as a
                # safety net.  It is never overwritten on idle transitions.
                from sase.ace.tui_activity import write_last_keypress, write_tui_pid

                write_last_keypress(activity_wall)
                # Re-write PID file periodically so it recovers if
                # deleted externally (e.g. stale cleanup race).
                write_tui_pid()
                # Only write the activity timestamp while the user is
                # active.  When idle, _check_idle_state already wrote
                # the idle transition time and we must not overwrite it
                # with the stale last-keypress time — is_idle() uses
                # the activity timestamp to detect manual/pinned idle
                # (epoch=0) vs natural idle.
                indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
                if not indicator._idle:
                    from sase.ace.tui_activity import write_activity_timestamp

                    write_activity_timestamp(activity_wall)
                self._last_activity_flush = now_mono
        self._check_idle_state(now_mono)
        self._countdown_remaining -= 1
        if self._countdown_remaining < 0:
            self._countdown_remaining = self.refresh_interval
        if self.current_tab == "changespecs":
            self._update_info_panel()  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._update_agents_info_panel()  # type: ignore[attr-defined]
        else:  # axe
            self._update_axe_info_panel()  # type: ignore[attr-defined]

    def _check_idle_state(self, now_mono: float) -> None:
        """Update the idle indicator based on elapsed inactivity."""
        if not hasattr(self, "_last_activity_time"):
            # Already manually marked inactive (I key) — leave idle on
            return
        elapsed = now_mono - self._last_activity_time
        idle = elapsed >= self._inactive_seconds
        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        was_idle = indicator._idle
        indicator.set_idle(idle)
        if idle != was_idle:
            from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

            write_idle_state(idle)
            if idle:
                # Write the current wall-clock time so is_idle() can
                # distinguish natural idle (non-zero epoch) from
                # manual/pinned idle (epoch=0).
                write_activity_timestamp(time.time())
                self._activity_log.record(ActivityEventType.IDLE_AUTO)

    def _record_user_activity(self) -> None:
        """Record user activity to reset the idle indicator.

        Called from on_key() for normal bindings and directly from
        priority-binding actions (e.g. tab switching) that bypass on_key().
        """
        # Pinned idle: only the I key can clear it, ignore all other activity.
        if getattr(self, "_pinned_idle", False):
            return
        # When manually idle (i key), _last_activity_time is absent.
        # Re-enable tracking — any user activity should exit idle mode.
        if not hasattr(self, "_last_activity_time"):
            self._last_activity_time = time.monotonic()
        self._last_activity_time = time.monotonic()
        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        was_idle = indicator._idle
        indicator.set_idle(False)
        if was_idle:
            # Flush to disk immediately when transitioning from idle to
            # active so external consumers (e.g. Telegram outbound chop)
            # see the change before their next poll cycle.
            from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

            write_idle_state(False)
            write_activity_timestamp(time.time())
            self._last_activity_flush = time.monotonic()
            self._activity_log.record(ActivityEventType.ACTIVE)

    def on_key(self, event: events.Key) -> None:
        """Handle key events, including fold, checkout, copy, and ancestry sub-keys."""
        self._record_user_activity()
        if self._fold_mode_active:
            if self._handle_fold_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._checkout_mode_active:
            if self._handle_checkout_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._copy_mode_active:
            if self._handle_copy_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif (
            self._ancestor_mode_active
            or self._child_mode_active
            or self._sibling_mode_active
        ):
            if self._handle_ancestry_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._leader_mode_active:
            if self._handle_leader_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._bang_mode_active:
            if self._handle_bang_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._custom_mode_active is not None:
            if self._handle_custom_mode_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif event.key in self._custom_mode_prefixes:
            self._custom_mode_active = self._custom_mode_prefixes[event.key]
            self._update_custom_mode_footer(self._custom_mode_active)  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()

    def on_input_changed(self, _event: Input.Changed) -> None:
        """Record activity when user types in a focused Input widget.

        Textual's ``Input`` widget calls ``event.stop()`` on key events,
        preventing them from bubbling to the App's ``on_key()`` handler.
        The ``Input.Changed`` message still bubbles, so we catch it here
        to keep the idle timer accurate while the user types.
        """
        self._record_user_activity()

    def on_change_spec_list_selection_changed(
        self, event: ChangeSpecList.SelectionChanged
    ) -> None:
        """Handle selection change in the ChangeSpec list widget."""
        if self.current_tab == "changespecs" and 0 <= event.index < len(
            self.changespecs
        ):
            # Push to history when clicking on a different CL
            if event.index != self.current_idx:
                self._push_changespec_to_history()  # type: ignore[attr-defined]
            self.current_idx = event.index

    def on_agent_list_selection_changed(
        self, event: AgentList.SelectionChanged
    ) -> None:
        """Handle selection change in the Agent list widget."""
        if self.current_tab != "agents":
            return

        # Convert local panel index to global index
        panel = event.panel
        indices = (
            self._main_panel_indices  # type: ignore[attr-defined]
            if panel == "main"
            else self._pinned_panel_indices  # type: ignore[attr-defined]
        )
        if 0 <= event.index < len(indices):
            global_idx = indices[event.index]
            if 0 <= global_idx < len(self._agents):
                # Update global index first to keep focus and selection in sync
                self.current_idx = global_idx
                # Switch panel focus if clicking in a different panel
                if self._pinned_panel_focused != panel:  # type: ignore[has-type]
                    self._pinned_panel_focused = panel  # type: ignore[has-type]
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

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
        from ..app import _MAX_LIST_WIDTH, _MIN_LIST_WIDTH

        width = max(_MIN_LIST_WIDTH, min(_MAX_LIST_WIDTH, event.width))
        list_container = self.query_one("#list-container")  # type: ignore[attr-defined]
        list_container.styles.width = width

    def on_agent_list_width_changed(self, event: AgentList.WidthChanged) -> None:
        """Handle width change from the agent list widget."""
        from ..app import _MAX_AGENT_LIST_WIDTH, _MIN_AGENT_LIST_WIDTH

        # Track per-panel widths and use the max (both panels share the container)
        if event.panel == "main":
            self._agent_main_panel_width = event.width  # type: ignore[attr-defined]
        else:
            self._agent_pinned_panel_width = event.width  # type: ignore[attr-defined]
        main_w = getattr(self, "_agent_main_panel_width", 0)
        pinned_w = getattr(self, "_agent_pinned_panel_width", 0)
        combined = max(main_w, pinned_w)
        width = max(_MIN_AGENT_LIST_WIDTH, min(_MAX_AGENT_LIST_WIDTH, combined))
        agent_list_container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        agent_list_container.styles.width = width

    def on_bg_cmd_list_selection_changed(
        self, event: BgCmdList.SelectionChanged
    ) -> None:
        """Handle selection change in the BgCmdList widget."""
        if self.current_tab == "axe":
            self.current_idx = event.index

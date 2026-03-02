"""Event handler mixin for the ace TUI app."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from textual import events

from ..widgets import (
    AgentList,
    BgCmdList,
    ChangeSpecList,
    InactiveIndicator,
    TabBar,
)

if TYPE_CHECKING:
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
    _tmux_mode_active: bool
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
    _inactive_seconds: int
    _last_activity_time: float
    _last_activity_flush: float

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

        # Tab-specific refreshes
        if self.current_tab == "changespecs":
            self._reload_and_reposition()  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._load_agents()  # type: ignore[attr-defined]
        # No else needed - axe display already refreshed by _load_axe_status()

    def _detect_input_activity(self) -> None:
        """Record activity when user types in a focused Input widget.

        Textual's ``Input`` widget stops key events from bubbling to the
        App, so ``on_key()`` never fires while the user types in an Input.
        This method polls the focused widget's state each countdown tick
        to detect typing activity.
        """
        from textual.widgets import Input

        try:
            focused = self.focused  # type: ignore[attr-defined]
        except Exception:
            return
        if focused is not None and isinstance(focused, Input):
            state = (focused.value, focused.cursor_position)
            prev = getattr(self, "_prev_input_state", None)
            if prev is not None and state != prev:
                self._record_user_activity()
            self._prev_input_state = state
        elif hasattr(self, "_prev_input_state"):
            del self._prev_input_state

    def _on_countdown_tick(self) -> None:
        """Countdown tick handler called every second."""
        now_mono = time.monotonic()
        self._detect_input_activity()
        if now_mono - self._last_activity_flush >= 10:
            if hasattr(self, "_last_activity_time"):
                from sase.ace.tui_activity import write_activity_timestamp

                activity_wall = time.time() - (now_mono - self._last_activity_time)
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
        indicator.set_idle(idle)

    def _record_user_activity(self) -> None:
        """Record user activity to reset the idle indicator.

        Called from on_key() for normal bindings and directly from
        priority-binding actions (e.g. tab switching) that bypass on_key().
        """
        self._last_activity_time = time.monotonic()
        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        indicator.set_idle(False)

    def on_key(self, event: events.Key) -> None:
        """Handle key events, including fold, checkout/tmux, copy, and ancestry sub-keys."""
        self._record_user_activity()
        if self._fold_mode_active:
            if self._handle_fold_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._checkout_mode_active or self._tmux_mode_active:
            if self._handle_checkout_tmux_key(event.key):  # type: ignore[attr-defined]
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
        if self.current_tab == "agents" and 0 <= event.index < len(self._agents):
            self.current_idx = event.index

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
                self.current_idx = 0  # Axe has no list
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

        width = max(_MIN_AGENT_LIST_WIDTH, min(_MAX_AGENT_LIST_WIDTH, event.width))
        agent_list_container = self.query_one("#agent-list-container")  # type: ignore[attr-defined]
        agent_list_container.styles.width = width

    def on_bg_cmd_list_selection_changed(
        self, event: BgCmdList.SelectionChanged
    ) -> None:
        """Handle selection change in the BgCmdList widget."""
        if self.current_tab == "axe":
            self._switch_to_axe_view(event.item)  # type: ignore[attr-defined]

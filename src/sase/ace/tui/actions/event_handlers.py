"""Event handler mixin for the ace TUI app."""

from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from textual import events

from ..activity_log import ActivityEventType, ActivityLog
from .navigation.jump_hints import normalize_jump_key
from ..util.nav_gate import NavigationGate
from ..widgets import (
    AgentList,
    BgCmdList,
    ChangeSpecList,
    InactiveIndicator,
    PromptInputBar,
    TabBar,
)

# Slow sanity-refresh floor: even when the inotify watcher is active and
# every dirty flag is clear we still reconcile every minute as a safety
# net for missed events (NFS, container bind-mount edge cases, etc.).
FULL_SANITY_REFRESH_SECONDS = 60.0
PROMPT_INPUT_DEFER_SECONDS = 0.25
log = logging.getLogger(__name__)

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
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _countdown_remaining: int
    _fold_mode_active: bool
    _checkout_mode_active: bool
    _copy_mode_active: bool
    _agents: list[Agent]
    _agents_loading: bool
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
    _entry_jump_mode_active: bool
    _inactive_seconds: int
    _last_activity_time: float
    _last_activity_flush: float
    _activity_log: ActivityLog
    _nav_gate: NavigationGate
    _dirty_changespecs: bool
    _dirty_agents: bool
    _dirty_axe: bool
    _artifact_change_defer_pending: bool
    _last_full_sanity_refresh: float

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

    def _record_jk_navigation(self) -> None:
        """Mark the wall-clock of the latest j/k action.

        Background reconcilers consult :class:`NavigationGate` to decide
        whether to fire now or defer until the user pauses, so the cursor
        highlight wins during long input bursts.
        """
        self._nav_gate.record()

    def _prompt_input_active(self) -> bool:
        """Return True while any prompt-like input surface is mounted."""
        if getattr(self, "_prompt_context", None) is not None:
            return True
        if getattr(self, "_approve_prompt_context", None) is not None:
            return True
        if getattr(self, "_plan_feedback_context", None) is not None:
            return True

        query = getattr(self, "query", None)
        if query is None:
            return False

        return bool(query(PromptInputBar))

    def _on_artifact_change(
        self, changed_paths: tuple[Path, ...] | None = None
    ) -> None:
        """Inotify dispatch: schedule a reconcile when the user is idle.

        Called on the UI thread by :class:`ArtifactWatcher` after coalescing
        a burst of file-system events.  Defers when the user is mid-burst
        on j/k so the reconcile lands during a pause rather than spiking
        latency in the middle of navigation.

        Phase 7: also flips the per-surface dirty flags so the auto-refresh
        tick (which is the watcher fallback) only does work for surfaces
        that actually changed.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            callback = (
                self._on_artifact_change
                if changed_paths is None
                else lambda: self._on_artifact_change(changed_paths)
            )
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                callback,
            )
            return
        self._schedule_artifact_graph_refresh(changed_paths)
        # The watcher cannot currently distinguish per-surface events
        # (artifacts vs project files vs axe state) without a deeper
        # rework of ``ArtifactWatcher``; mark every surface dirty so the
        # next auto-refresh tick reconciles whatever the user has open.
        self._dirty_changespecs = True
        self._dirty_agents = True
        self._dirty_axe = True
        if self._prompt_input_active():
            pending = set(getattr(self, "_artifact_change_deferred_paths", ()))
            pending.update(changed_paths or ())
            self._artifact_change_deferred_paths = tuple(sorted(pending))
            if not self._artifact_change_defer_pending:
                self._artifact_change_defer_pending = True
                self.set_timer(  # type: ignore[attr-defined]
                    PROMPT_INPUT_DEFER_SECONDS,
                    self._on_artifact_change_deferred,
                )
            return
        # Existing schedulers already coalesce stampedes via the
        # ``_*_loading`` / ``_*_refresh_pending`` machinery so a flurry of
        # inotify wakeups still triggers at most one in-flight reload plus
        # one follow-up.
        self._schedule_agents_async_refresh()  # type: ignore[attr-defined]
        self._schedule_changespecs_async_refresh()  # type: ignore[attr-defined]

    def _schedule_artifact_graph_refresh(
        self, changed_paths: tuple[Path, ...] | None
    ) -> None:
        """Refresh unified graph rows for explicit source changes.

        The compatibility agent list index remains an implementation detail for
        startup, while source-change events update the unified graph directly.
        Pure selection/highlight movement never calls this path.
        """

        if not changed_paths:
            return

        def _refresh() -> None:
            from ..artifact_graph_refresh import (
                default_artifact_index_path,
                refresh_artifact_graph_for_paths,
            )

            try:
                refresh_artifact_graph_for_paths(
                    default_artifact_index_path(), changed_paths
                )
            except Exception:
                log.debug("targeted artifact graph refresh failed", exc_info=True)

        run_worker = getattr(self, "run_worker", None)
        if callable(run_worker):
            run_worker(_refresh, thread=True, exclusive=False, group="artifact-graph")
        else:
            _refresh()

    def _on_artifact_change_deferred(self) -> None:
        """Timer-fired wrapper that clears the dedup flag before reentering.

        Clearing the flag *on entry* means a single fresh defer timer can
        be scheduled if the prompt is still active when ``_on_artifact_change``
        re-runs, while back-to-back watcher events that arrive between
        scheduling and firing collapse into the existing pending timer.
        """
        self._artifact_change_defer_pending = False
        changed_paths = getattr(self, "_artifact_change_deferred_paths", ())
        self._artifact_change_deferred_paths = ()
        self._on_artifact_change(changed_paths or None)

    def _watcher_active(self) -> bool:
        """Return True when the inotify watcher is currently driving refreshes."""
        return getattr(self, "_fs_watcher", None) is not None

    async def _on_auto_refresh(self) -> None:
        """Auto-refresh handler called by timer.

        When the user is mid-burst on j/k the refresh defers itself for the
        remainder of the navigation window plus a small overshoot.  A new
        ``set_timer`` call schedules a single retry; if the user is *still*
        navigating when that fires, the same gate will defer it again.

        Phase 7: when the inotify watcher is active each surface's refresh
        is gated on its dirty flag; flags clear after the refresh runs.
        Every ``FULL_SANITY_REFRESH_SECONDS`` we ignore the gate and run
        a full reconcile to recover from any missed events.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._on_auto_refresh)  # type: ignore[attr-defined]
            return

        self._countdown_remaining = self.refresh_interval
        if self._prompt_input_active():
            return

        watcher_active = self._watcher_active()
        now_mono = time.monotonic()
        sanity_due = (
            now_mono - getattr(self, "_last_full_sanity_refresh", 0.0)
            >= FULL_SANITY_REFRESH_SECONDS
        )

        def _should_refresh(flag_name: str) -> bool:
            if not watcher_active or sanity_due:
                return True
            return bool(getattr(self, flag_name, True))

        # Always poll axe status regardless of tab (for STARTING/STOPPING
        # transitions) — but skip the disk poll on idle ticks when the
        # watcher is active and nothing about axe has changed.
        if _should_refresh("_dirty_axe"):
            await self._load_axe_status_async()  # type: ignore[attr-defined]
            self._dirty_axe = False

        # Poll agent completions for notifications (regardless of tab).
        # Notification freshness rides the agent dirty flag because a
        # done.json write triggers an agents-dir watcher event.
        if _should_refresh("_dirty_agents"):
            await self._poll_agent_completions()  # type: ignore[attr-defined]

        # Skip changespec/agent refresh if the user is in a transient input
        # mode (hint bar or similar is active).
        if getattr(self, "_hint_mode_active", False):
            return
        if getattr(self, "_entry_jump_mode_active", False):
            return
        if getattr(self, "_accept_mode_active", False):
            return

        # Skip if a background agent load is already in progress
        if self._agents_loading:
            return

        agents_due = _should_refresh("_dirty_agents")
        if agents_due:
            self._agents_loading = True
            try:
                await self._load_agents_async()  # type: ignore[attr-defined]
            finally:
                self._agents_loading = False
            self._dirty_agents = False

        if self.current_tab == "changespecs" and _should_refresh("_dirty_changespecs"):
            await self._reload_and_reposition_async()  # type: ignore[attr-defined]
            self._dirty_changespecs = False

        if sanity_due:
            self._last_full_sanity_refresh = now_mono

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
        if self._entry_jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self._handle_entry_jump_key(key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._fold_mode_active:
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
        """Handle selection change in the Agent list widget.

        Each AgentList instance is a tag-bucket panel; ``event.index`` is
        local to that panel, so we translate it back to a global agent
        index using the panel's filtered slice.
        """
        if self.current_tab != "agents":
            return

        from ..models.agent_panels import agents_for_panel
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

        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == panel_key]
        panel_agents = agents_for_panel(self._agents, panel_key)

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

        # Switching panel via mouse click moves panel focus too.
        if panel_idx != self._panel_group.focused_idx:  # type: ignore[attr-defined]
            self._panel_group.focused_idx = panel_idx  # type: ignore[attr-defined]

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

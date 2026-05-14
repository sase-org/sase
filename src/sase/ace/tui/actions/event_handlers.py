"""Event handler mixin for the ace TUI app."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from textual import events

from ..activity_log import ActivityEventType, ActivityLog
from .navigation.jump_hints import normalize_jump_key
from ..util.nav_gate import NavigationGate
from ..util.trace import trace_event
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
DAEMON_REFRESH_EVENT_BATCH_LIMIT = 1
DAEMON_REFRESH_MAX_EVENTS = 64

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
        targets = self._dirty_surfaces_for_paths(changed_paths)
        if "changespecs" in targets:
            self._dirty_changespecs = True
        if "agents" in targets:
            self._dirty_agents = True
        if "axe" in targets:
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

    def _dirty_surfaces_for_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> set[str]:
        """Map watcher paths to the smallest ACE surface set we can infer."""
        if not changed_paths:
            return {"changespecs", "agents", "axe"}

        targets: set[str] = set()
        projects_root = Path.home() / ".sase" / "projects"
        beads_dir = Path.cwd() / "sdd" / "beads"
        for path in changed_paths:
            parts = path.parts
            if beads_dir in (path, *path.parents):
                targets.add("changespecs")
                continue
            if "artifacts" in parts:
                targets.add("agents")
                continue
            if path.suffix in {".sase", ".gp"}:
                targets.update({"changespecs", "axe"})
                continue
            if projects_root in (path, *path.parents):
                targets.update({"changespecs", "agents", "axe"})
                continue
            targets.update({"changespecs", "agents", "axe"})
        return targets or {"changespecs", "agents", "axe"}

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

    def _daemon_surface_snapshot(self, surface: str) -> Any | None:
        attr = {
            "agents": "_agents_provider_snapshot",
            "changespecs": "_changespec_provider_snapshot",
            "notifications": "_notification_provider_snapshot",
        }.get(surface)
        return getattr(self, attr, None) if attr else None

    def _daemon_surface_clean_candidate(self, surface: str) -> bool:
        snapshot = self._daemon_surface_snapshot(surface)
        provider = getattr(snapshot, "provider", None)
        return bool(
            snapshot is not None
            and getattr(provider, "source", None) == "daemon"
            and getattr(getattr(provider, "fallback", None), "reason", None) is None
        )

    async def _daemon_refresh_probe(
        self,
        surface: str,
        *,
        collections: list[str],
    ) -> Literal["legacy", "clean", "applied", "poll"]:
        """Use daemon events as the no-change refresh gate for one surface."""
        if not self._daemon_surface_clean_candidate(surface):
            return "legacy"

        import asyncio

        snapshot = self._daemon_surface_snapshot(surface)
        client = getattr(self, "_daemon_read_client", None)
        if client is None:
            from sase.daemon.client import LocalDaemonClient

            client = LocalDaemonClient()
        event_ids = getattr(self, "_daemon_refresh_event_ids", None)
        if event_ids is None:
            event_ids = {}
            self._daemon_refresh_event_ids = event_ids  # type: ignore[attr-defined]
        after_event_id = event_ids.get(surface)

        trace_event(
            "ace.daemon_refresh_probe",
            surface=surface,
            snapshot_id=getattr(snapshot, "snapshot_id", None),
            after_event_id=after_event_id,
        )
        try:
            batches = await asyncio.to_thread(
                client.read_events,
                DAEMON_REFRESH_EVENT_BATCH_LIMIT,
                after_event_id=after_event_id,
                snapshot_id=getattr(snapshot, "snapshot_id", None),
                collections=collections,
                max_events=DAEMON_REFRESH_MAX_EVENTS,
            )
        except Exception as exc:
            trace_event(
                "ace.daemon_refresh_fallback",
                surface=surface,
                reason=getattr(exc, "fallback_reason", None)
                or getattr(exc, "code", None)
                or type(exc).__name__,
            )
            return "poll"

        for batch in batches:
            next_event_id = batch.get("next_event_id")
            if isinstance(next_event_id, str) and next_event_id:
                event_ids[surface] = next_event_id

        events = [
            event
            for batch in batches
            for event in batch.get("events", [])
            if self._daemon_event_affects_refresh(event)
        ]
        if not events:
            trace_event(
                "ace.daemon_refresh_noop",
                surface=surface,
                snapshot_id=getattr(snapshot, "snapshot_id", None),
                event_batches=len(batches),
            )
            return "clean"

        trace_event(
            "ace.daemon_delta_batch",
            surface=surface,
            event_count=len(events),
            snapshot_id=getattr(snapshot, "snapshot_id", None),
        )
        if surface == "agents" and self._apply_agents_daemon_event_batches(batches):
            return "applied"
        return "poll"

    def _daemon_event_affects_refresh(self, event: Any) -> bool:
        if not isinstance(event, dict):
            return False
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return False
        payload_type = str(payload.get("type", ""))
        if payload_type == "heartbeat":
            return False
        return bool(payload)

    def _apply_agents_daemon_event_batches(self, batches: list[dict[str, Any]]) -> bool:
        """Patch the current Agents rows from daemon deltas when possible."""
        from ..data_providers import apply_daemon_agent_events
        from ..models.agent_loader import AgentLoadState

        current_agents = list(getattr(self, "_agents", []))
        next_agents = current_agents
        for batch in batches:
            for event in batch.get("events", []):
                if not self._daemon_event_affects_refresh(event):
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                if not isinstance(payload, dict):
                    return False
                if "delta" not in payload and "resync_required" not in payload:
                    trace_event(
                        "agents.daemon_delta_resync",
                        reason="unsupported_agent_event_shape",
                    )
                    return False
            result = apply_daemon_agent_events(next_agents, batch)
            if result.resync_required:
                trace_event(
                    "agents.daemon_delta_resync",
                    reason=result.resync_reason,
                )
                return False
            next_agents = result.agents

        if self._agents_delta_signature(next_agents) == self._agents_delta_signature(
            current_agents
        ):
            trace_event("agents.daemon_delta_noop")
            return True

        on_agents_tab = getattr(self, "current_tab", None) == "agents"
        selected_identity = None
        if (
            on_agents_tab
            and current_agents
            and 0 <= getattr(self, "current_idx", -1) < len(current_agents)
        ):
            selected_identity = current_agents[self.current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        load_state = getattr(self, "_agent_load_state", None) or AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="daemon_projection",
            used_artifact_index=False,
        )
        self._apply_loaded_agents(  # type: ignore[attr-defined]
            next_agents,
            [],
            on_agents_tab,
            selected_identity,
            load_state=load_state,
        )
        trace_event("agents.daemon_delta_applied", row_count=len(next_agents))
        return True

    def _agents_delta_signature(self, agents: list[Any]) -> tuple[tuple[Any, ...], ...]:
        return tuple(
            (
                getattr(agent, "identity", None),
                getattr(agent, "status", None),
                getattr(agent, "tag", None),
                getattr(agent, "pid", None),
                getattr(agent, "raw_suffix", None),
            )
            for agent in agents
        )

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

        agents_due = _should_refresh("_dirty_agents")
        if agents_due:
            notification_refresh = await self._daemon_refresh_probe(
                "notifications",
                collections=["notifications"],
            )
            if notification_refresh in {"legacy", "poll"}:
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

        if agents_due:
            agent_refresh = await self._daemon_refresh_probe(
                "agents",
                collections=["agents", "artifacts"],
            )
            if agent_refresh in {"legacy", "poll"}:
                self._agents_loading = True
                try:
                    await self._load_agents_async()  # type: ignore[attr-defined]
                finally:
                    self._agents_loading = False
            self._dirty_agents = False

        if self.current_tab == "changespecs" and _should_refresh("_dirty_changespecs"):
            changespec_refresh = await self._daemon_refresh_probe(
                "changespecs",
                collections=["changespecs"],
            )
            if changespec_refresh in {"legacy", "poll"}:
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
            self._patch_agent_runtime_rows()  # type: ignore[attr-defined]
        else:  # axe
            self._update_axe_info_panel()  # type: ignore[attr-defined]
            # Stream live output for an active chop run without waiting for
            # the slower full-fleet refresh interval.
            self._axe_live_tick()  # type: ignore[attr-defined]

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
        panel_agents = agents_for_panel(
            self._agents,
            panel_key,
            merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
        )

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
        ):
            guard = getattr(self, "_guard_agent_navigation_for_artifact_viewer", None)
            if callable(guard) and guard():
                return

        # Switching panel via mouse click moves panel focus too.
        if panel_idx != self._panel_group.focused_idx:  # type: ignore[attr-defined]
            self._panel_group.focused_idx = panel_idx  # type: ignore[attr-defined]

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

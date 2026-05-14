"""Refresh, watcher, and daemon event handlers for the ACE TUI."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

from ..util.trace import trace_event
from ._event_base import EventHandlersBase

# Slow sanity-refresh floor: even when the inotify watcher is active and
# every dirty flag is clear we still reconcile every minute as a safety
# net for missed events (NFS, container bind-mount edge cases, etc.).
FULL_SANITY_REFRESH_SECONDS = 60.0
PROMPT_INPUT_DEFER_SECONDS = 0.25
DAEMON_REFRESH_EVENT_BATCH_LIMIT = 1
DAEMON_REFRESH_MAX_EVENTS = 64


class EventRefreshMixin(EventHandlersBase):
    """Mixin providing watcher, daemon, and refresh timer callbacks."""

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

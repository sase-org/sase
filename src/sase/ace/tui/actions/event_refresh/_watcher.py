"""Watcher dirty-surface routing for sase's TUI refreshes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time

from sase.core.paths import sase_projects_dir, sase_subdir

from ._artifact_delta import EventArtifactDeltaMixin
from ._artifact_paths import artifact_path_affects_agents
from ._constants import PROMPT_INPUT_DEFER_SECONDS, _LIVE_REPLY_ARTIFACT_NAMES
from ._sdd_paths import cached_sdd_beads_dir
from ...util.trace import is_enabled as tui_trace_enabled, trace_event

_WATCHER_TRACE_SAMPLE_SECONDS = 10.0


class EventWatcherRefreshMixin(EventArtifactDeltaMixin):
    """Mixin for watcher callbacks and dirty-surface mapping."""

    def _sample_watcher_stats_for_trace(self) -> None:
        """Emit coarse per-instance watcher counter deltas on auto-refresh ticks."""
        if not tui_trace_enabled():
            return
        now = time.monotonic()
        previous_sample = float(getattr(self, "_watcher_trace_sample_mono", 0.0) or 0.0)
        if now - previous_sample < _WATCHER_TRACE_SAMPLE_SECONDS:
            return
        self._watcher_trace_sample_mono = now
        baselines = getattr(self, "_watcher_trace_baselines", None)
        if not isinstance(baselines, dict):
            baselines = {}
            self._watcher_trace_baselines = baselines

        for source, attr in (
            ("artifact", "_fs_watcher"),
            ("prompt_source", "_prompt_source_watcher"),
        ):
            watcher = getattr(self, attr, None)
            previous = baselines.get(source)
            observed = watcher
            if observed is None and isinstance(previous, tuple) and previous:
                observed = previous[0]
            stats_method = getattr(observed, "stats", None)
            totals = stats_method() if callable(stats_method) else {}
            totals = {
                key: int(value)
                for key, value in totals.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
            instance_changed = watcher is not None and (
                not isinstance(previous, tuple) or previous[0] is not watcher
            )
            baseline_only = watcher is not None and (
                not isinstance(previous, tuple) or previous[0] is not watcher
            )
            counter_reset = False
            if isinstance(previous, tuple) and previous[0] is observed:
                old_totals = previous[1]
                interval_start = float(previous[2])
                counter_reset = any(
                    totals.get(key, 0) < old_totals.get(key, 0)
                    for key in old_totals.keys() | totals.keys()
                )
                deltas = {
                    key: (
                        totals.get(key, 0)
                        if counter_reset
                        else totals.get(key, 0) - old_totals.get(key, 0)
                    )
                    for key in old_totals.keys() | totals.keys()
                }
            else:
                interval_start = now
                deltas = dict.fromkeys(totals, 0)
            trace_event(
                "refresh.watcher_stats",
                watcher_source=source,
                watcher_active=watcher is not None,
                instance_changed=instance_changed,
                baseline_only=baseline_only,
                counter_reset=counter_reset,
                interval_start_mono=interval_start,
                interval_end_mono=now,
                interval_seconds=max(0.0, now - interval_start),
                counter_deltas=deltas,
                counter_totals=totals,
            )
            if watcher is None:
                baselines.pop(source, None)
            else:
                baselines[source] = (watcher, totals, now)

    def _on_artifact_change(
        self, changed_paths: tuple[Path, ...] | None = None
    ) -> None:
        """Inotify dispatch: mark dirty surfaces when the user is idle.

        Called on the UI thread by :class:`ArtifactWatcher` after coalescing
        a burst of file-system events.  Defers when the user is mid-burst
        on j/k so any immediate reconcile lands during a pause rather than
        spiking latency in the middle of navigation.

        Agents changes only set ``_dirty_agents``; the tab-switch path,
        auto-refresh gate, debounce floor, and sanity refresh decide when
        the expensive loader actually runs.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            callback: Callable[[], None]
            if changed_paths is None:
                callback = self._on_artifact_change
            else:
                deferred_paths = changed_paths

                def callback() -> None:
                    self._on_artifact_change(deferred_paths)

            self.set_timer(  # type: ignore[attr-defined]
                delay,
                callback,
            )
            return
        changed_paths = self._filter_expected_self_deletion_paths(changed_paths)
        if changed_paths is not None and not changed_paths:
            return
        self._route_live_reply_artifact_paths(changed_paths)
        targets = self._dirty_surfaces_for_paths(changed_paths)
        if not targets:
            return
        if "artifacts" in targets:
            self._dirty_patches = True
            self._dirty_changespecs = True  # type: ignore[attr-defined] # legacy compatibility alias
        if "agents" in targets:
            self._dirty_agents = True
            self._enqueue_agent_artifact_delta_paths(changed_paths)
        if "axe" in targets:
            self._dirty_axe = True
        if "notifications" in targets:
            self._dirty_notifications = True
            schedule_poll = getattr(self, "_schedule_notification_poll", None)
            if callable(schedule_poll):
                # File mutations may replace or cancel the cached nearest
                # deadline. Refresh this small surface immediately even when
                # general auto-refresh is disabled.
                schedule_poll(source="watcher")
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
        # Patch refreshes are cheap enough to keep immediate and already
        # coalesce through their pending/loading guard. Agents reloads are
        # intentionally consumed by the auto-refresh/tab-switch gates above.
        if "artifacts" in targets:
            schedule_patches = getattr(self, "_schedule_patches_async_refresh", None)
            if callable(schedule_patches):
                schedule_patches()
                return
            schedule_changespecs = getattr(  # legacy compatibility alias
                self,
                "_schedule_changespecs_async_refresh",  # legacy compatibility alias
                None,
            )
            if callable(schedule_changespecs):  # legacy compatibility alias
                schedule_changespecs()  # legacy compatibility alias

    def _route_live_reply_artifact_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> None:
        """Send selected reply-file events to the prompt panel's local follower."""
        if not changed_paths or not any(
            path.name in _LIVE_REPLY_ARTIFACT_NAMES for path in changed_paths
        ):
            return
        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return
        try:
            detail = query_one("#agent-detail-panel")
        except Exception:
            return
        get_panel = getattr(detail, "_deck_source_panel", None)
        if not callable(get_panel):
            return
        try:
            panel = get_panel()
        except Exception:
            return
        handler = getattr(panel, "on_live_reply_artifact_change", None)
        if callable(handler):
            handler(changed_paths)

    def _dirty_surfaces_for_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> set[str]:
        """Map watcher paths to the smallest ACE surface set we can infer."""
        if not changed_paths:
            return {"artifacts", "agents", "axe", "notifications"}

        targets: set[str] = set()
        ignored_artifact_path = False
        projects_root = sase_projects_dir()
        notifications_root = sase_subdir("notifications")
        beads_dir = cached_sdd_beads_dir(self)
        for path in changed_paths:
            parts = path.parts
            if notifications_root in (path, *path.parents):
                targets.add("notifications")
                continue
            if beads_dir in (path, *path.parents):
                targets.add("artifacts")
                continue
            if "artifacts" in parts:
                if artifact_path_affects_agents(path):
                    targets.add("agents")
                else:
                    ignored_artifact_path = True
                continue
            if path.suffix in {".sase", ".gp"}:
                targets.update({"artifacts", "axe"})
                continue
            if projects_root in (path, *path.parents):
                targets.update({"artifacts", "axe"})
                continue
            targets.update({"artifacts", "axe"})
        if targets:
            return targets
        if ignored_artifact_path:
            return set()
        return {"artifacts", "agents", "axe"}

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

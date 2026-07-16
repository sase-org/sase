"""Watcher dirty-surface routing for ACE TUI refreshes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.core.paths import sase_projects_dir, sase_subdir

from ._artifact_delta import EventArtifactDeltaMixin
from ._artifact_paths import artifact_path_affects_agents
from ._constants import PROMPT_INPUT_DEFER_SECONDS
from ._sdd_paths import cached_sdd_beads_dir


class EventWatcherRefreshMixin(EventArtifactDeltaMixin):
    """Mixin for watcher callbacks and dirty-surface mapping."""

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
        targets = self._dirty_surfaces_for_paths(changed_paths)
        if not targets:
            return
        if "changespecs" in targets:
            self._dirty_changespecs = True
        if "agents" in targets:
            self._dirty_agents = True
            self._enqueue_agent_artifact_delta_paths(changed_paths)
        if "axe" in targets:
            self._dirty_axe = True
        if "notifications" in targets:
            self._dirty_notifications = True
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
        # ChangeSpec refreshes are cheap enough to keep immediate and already
        # coalesce through their pending/loading guard. Agents reloads are
        # intentionally consumed by the auto-refresh/tab-switch gates above.
        if "changespecs" in targets:
            self._schedule_changespecs_async_refresh()  # type: ignore[attr-defined]

    def _dirty_surfaces_for_paths(
        self, changed_paths: tuple[Path, ...] | None
    ) -> set[str]:
        """Map watcher paths to the smallest ACE surface set we can infer."""
        if not changed_paths:
            return {"changespecs", "agents", "axe", "notifications"}

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
                targets.add("changespecs")
                continue
            if "artifacts" in parts:
                if artifact_path_affects_agents(path):
                    targets.add("agents")
                else:
                    ignored_artifact_path = True
                continue
            if path.suffix in {".sase", ".gp"}:
                targets.update({"changespecs", "axe"})
                continue
            if projects_root in (path, *path.parents):
                targets.update({"changespecs", "agents", "axe"})
                continue
            targets.update({"changespecs", "agents", "axe"})
        if targets:
            return targets
        if ignored_artifact_path:
            return set()
        return {"changespecs", "agents", "axe"}

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

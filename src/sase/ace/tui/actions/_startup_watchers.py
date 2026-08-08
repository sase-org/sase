"""Filesystem watcher helpers used by ACE startup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.paths import sase_projects_dir, sase_subdir

from ..util.fs_watcher import ArtifactWatcher

if TYPE_CHECKING:
    from textual.timer import Timer

log = logging.getLogger(__name__)


class StartupWatchersMixin:
    """Mixin for artifact and prompt-source watcher lifecycle."""

    _fs_watcher: ArtifactWatcher | None
    _sdd_beads_dir: Path | None
    _prompt_source_watcher: ArtifactWatcher | None
    _prompt_source_watcher_active: bool
    _prompt_source_watched_projects: set[str | None]
    _prompt_source_debounce_timer: Timer | None
    _prompt_source_debounce_config_dirty: bool

    def _start_artifact_watcher(self: Any) -> None:
        """Spin up an inotify watcher on ``~/.sase/projects/`` if supported.

        Falls back silently when inotify is unavailable; the auto-refresh
        timer remains the polling safety net in that case.
        """
        from .event_refresh._sdd_paths import resolve_current_sdd_beads_dir

        if self._fs_watcher is not None:
            return
        projects_dir = sase_projects_dir()
        if not projects_dir.exists():
            return
        # Watch each project's artifacts dir directly.  inotify on a
        # parent dir only fires for direct-child events, so watching
        # ``projects/`` would miss writes inside ``projects/<p>/artifacts/``.
        watch_paths: list[Path] = []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            artifacts_dir = project_dir / "artifacts"
            if artifacts_dir.is_dir():
                watch_paths.append(artifacts_dir)
            # Project spec files live directly in ``project_dir``;
            # watching the dir picks up RUNNING-field updates.
            watch_paths.append(project_dir)
        beads_dir = resolve_current_sdd_beads_dir()
        self._sdd_beads_dir = beads_dir
        if beads_dir.is_dir():
            watch_paths.append(beads_dir)
        notifications_dir = sase_subdir("notifications")
        if notifications_dir.is_dir():
            watch_paths.append(notifications_dir)
        if not watch_paths:
            return
        watcher = ArtifactWatcher(
            watch_paths,
            on_change=self._on_artifact_change,
            schedule_callback=self.call_from_thread,
        )
        if watcher.start():
            self._fs_watcher = watcher

    def _stop_artifact_watcher(self: Any) -> None:
        """Tear down the inotify watcher on quit."""
        watcher = self._fs_watcher
        if watcher is None:
            return
        self._fs_watcher = None
        try:
            watcher.stop()
        except Exception:
            log.exception("Failed to stop artifact watcher cleanly")

    def _start_prompt_source_watcher(self: Any) -> None:
        """Spin up an inotify watcher on editable prompt/snippet sources."""
        if self._prompt_source_watcher is not None:
            return
        from ..prompt_catalog import prompt_source_watch_paths

        watch_paths = prompt_source_watch_paths(self._prompt_catalog_projects)
        if not watch_paths:
            self._prompt_source_watcher_active = False
            return
        watcher = ArtifactWatcher(
            watch_paths,
            on_change=self._on_prompt_source_change,
            schedule_callback=self.call_from_thread,
        )
        if watcher.start():
            self._prompt_source_watcher = watcher
            self._prompt_source_watcher_active = True
            self._prompt_source_watched_projects = set(self._prompt_catalog_projects)
        else:
            self._prompt_source_watcher_active = False

    def _restart_prompt_source_watcher(self: Any) -> None:
        """Restart prompt watcher after the requested project set grows."""
        self._stop_prompt_source_watcher()
        self._start_prompt_source_watcher()

    def _stop_prompt_source_watcher(self: Any) -> None:
        """Tear down the prompt-source inotify watcher on quit."""
        timer = self._prompt_source_debounce_timer
        if timer is not None:
            timer.stop()
            self._prompt_source_debounce_timer = None
        self._prompt_source_debounce_config_dirty = False
        watcher = self._prompt_source_watcher
        self._prompt_source_watcher = None
        self._prompt_source_watcher_active = False
        self._prompt_source_watched_projects = set()
        if watcher is None:
            return
        try:
            watcher.stop()
        except Exception:
            log.exception("Failed to stop prompt-source watcher cleanly")

    def _on_prompt_source_change(self: Any, changed_paths: tuple[Any, ...]) -> None:
        """Debounced callback for editable prompt/snippet source changes."""
        from pathlib import Path

        from ..prompt_catalog import (
            PROMPT_SOURCE_DEBOUNCE_S,
            PROMPT_SOURCE_SUFFIXES,
            prompt_source_change_touches_config,
        )

        paths = tuple(Path(path) for path in changed_paths)
        config_dirty = prompt_source_change_touches_config(paths)
        if not config_dirty and not any(
            not path.suffix or path.suffix.lower() in PROMPT_SOURCE_SUFFIXES
            for path in paths
        ):
            return
        self._prompt_source_debounce_config_dirty = (
            self._prompt_source_debounce_config_dirty or config_dirty
        )
        timer = self._prompt_source_debounce_timer
        if timer is not None:
            timer.stop()
        self._prompt_source_debounce_timer = self.set_timer(
            PROMPT_SOURCE_DEBOUNCE_S,
            self._fire_prompt_source_debounce,
            name="prompt-source-debounce",
        )

    def _fire_prompt_source_debounce(self: Any) -> None:
        """Start one coalesced prompt catalog rebuild after source changes."""
        self._prompt_source_debounce_timer = None
        config_dirty = self._prompt_source_debounce_config_dirty
        self._prompt_source_debounce_config_dirty = False
        self._prompt_catalog_generation += 1
        if config_dirty:
            invalidate_glossary = getattr(
                self,
                "_invalidate_prompt_glossary_catalogs",
                None,
            )
            if callable(invalidate_glossary):
                invalidate_glossary(reason="prompt_source_change")
        self._schedule_prompt_catalog_rebuild(
            reason="prompt_source_change",
            config_dirty=config_dirty,
        )

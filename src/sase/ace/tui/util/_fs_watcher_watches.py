"""Watch-table management for the fs_watcher split."""

from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Iterable
from pathlib import Path

from sase.core.agent_artifact_shards import (
    is_agent_artifact_dir_name,
    iter_startup_ace_run_shard_watch_paths,
)

from ._fs_watcher_common import is_ignored_watch_name, load_libc
from ._fs_watcher_core import WatcherCore

log = logging.getLogger(__name__)

# Hard cap on simultaneously-installed inotify watches. Each launched
# agent's artifact tree adds dozens of watches; without a ceiling the
# kernel watch table grows unbounded over a long ACE session.
MAX_INOTIFY_WATCHES = 4096


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _watch_key(path: Path) -> str:
    return str(path)


class WatcherWatches(WatcherCore):
    """Watch-table mixin: install, drop, and grow inotify watches."""

    def ensure_watches(self, paths: Iterable[Path | str]) -> int:
        """Install watches for existing paths that are not already watched.

        Safe to call from the UI thread. Already-watched paths are a cheap
        no-op and do not consume the watch budget. Returns how many new
        watches were installed. A watcher that never started, or has been
        stopped, is a no-op that returns ``0``.
        """
        if self._stop_event.is_set() or self._fd < 0:
            return 0
        libc = load_libc()
        if libc is None:
            return 0
        fd = self._fd
        if fd < 0:
            return 0
        installed = 0
        for path in paths:
            installed += self._add_watch_path(libc, fd, Path(path))
        return installed

    def prune_agent_dir_watches(self, terminal_dirs: Iterable[Path | str]) -> int:
        """Drop watches on caller-identified terminal 14-digit agent dirs.

        Only paths whose final component is a 14-digit agent artifact
        directory name are removed, and only when the caller positively
        names them. Shard and project watches are left intact. Returns
        how many watches were removed.
        """
        if self._stop_event.is_set() or self._fd < 0:
            return 0
        libc = load_libc()
        fd = self._fd
        pruned = 0
        for raw_path in terminal_dirs:
            path = Path(raw_path)
            if not is_agent_artifact_dir_name(path.name):
                continue
            with self._watch_lock:
                wd = self._wd_by_path.get(_watch_key(path))
            if wd is None:
                continue
            self._remove_watch(libc, fd, wd)
            pruned += 1
        return pruned

    def _add_watch_path(self, libc: ctypes.CDLL, fd: int, path: Path) -> int:
        """Install one watch without walking existing descendants."""
        key = _watch_key(path)
        with self._watch_lock:
            if key in self._wd_by_path:
                return 0
        try:
            if not path.exists():
                return 0
        except OSError:
            return 0

        with self._watch_lock:
            if key in self._wd_by_path:
                return 0
            if len(self._watch_paths_by_wd) >= MAX_INOTIFY_WATCHES:
                if not self._watch_cap_warning_emitted:
                    log.warning(
                        "inotify watch cap (%d) reached; skipping new watches until pruned",
                        MAX_INOTIFY_WATCHES,
                    )
                    self._watch_cap_warning_emitted = True
                return 0

            wd = libc.inotify_add_watch(fd, str(path).encode("utf-8"), self._mask)
            if wd < 0:
                err = ctypes.get_errno()
                log.debug("inotify_add_watch(%s) failed: errno=%d", path, err)
                return 0
            previous = self._watch_paths_by_wd.get(wd)
            if previous is not None:
                previous_key = _watch_key(previous)
                if previous_key != key:
                    self._wd_by_path.pop(previous_key, None)
            self._watch_paths_by_wd[wd] = path
            self._wd_by_path[key] = wd
            return 1

    def _remove_watch(self, libc: ctypes.CDLL | None, fd: int, wd: int) -> None:
        """Drop *wd* from the tracking dict and call ``inotify_rm_watch``.

        ``IN_IGNORED`` events arrive after the kernel has already detached
        the watch (e.g. because the directory was deleted), so the
        ``inotify_rm_watch`` call is best-effort: a failing call is
        expected for the auto-detached case and is silently ignored.
        """
        with self._watch_lock:
            path = self._watch_paths_by_wd.pop(wd, None)
            if path is not None:
                key = _watch_key(path)
                if self._wd_by_path.get(key) == wd:
                    self._wd_by_path.pop(key, None)
            if libc is None or not hasattr(libc, "inotify_rm_watch") or fd < 0:
                return
            try:
                libc.inotify_rm_watch(fd, wd)
            except OSError:
                pass

    def _iter_startup_watch_paths(self) -> Iterable[Path]:
        """Yield bounded startup watch paths.

        Artifact roots need one extra level so writes under pre-existing
        workflow directories (``artifacts/ace-run/<new-ts>/...``) wake the UI.
        This intentionally stops before timestamp/history directories.
        """
        for path in self._paths:
            yield path
            if path.name != "artifacts":
                continue
            try:
                children = tuple(path.iterdir())
            except OSError:
                continue
            for child in children:
                try:
                    if child.is_dir():
                        yield child
                        if child.name == "ace-run":
                            yield from self._iter_recent_ace_run_shard_watch_paths(
                                child
                            )
                except OSError:
                    continue

    def _iter_recent_ace_run_shard_watch_paths(
        self, workflow_dir: Path
    ) -> Iterable[Path]:
        """Yield bounded existing month/day shard dirs for startup watches."""
        yield from iter_startup_ace_run_shard_watch_paths(workflow_dir)

    def _add_watch_tree(self, libc: ctypes.CDLL, fd: int, path: Path) -> int:
        """Install watches for a newly-created or moved directory tree.

        Startup uses shallow watches only so it never walks historical
        artifact trees. Recursive installation is reserved for directories
        that appear after the watcher is already running, which keeps normal
        startup cheap while still following freshly-created agent artifact
        directories. Recursion stops at a 14-digit per-agent artifact
        directory: loader-visible markers live at that directory's top level.
        """

        installed = 0
        stack = [path]
        while stack:
            current = stack.pop()
            installed += self._add_watch_path(libc, fd, current)
            if is_agent_artifact_dir_name(current.name):
                continue
            try:
                children = tuple(
                    child
                    for child in current.iterdir()
                    if _path_is_dir(child) and not is_ignored_watch_name(child.name)
                )
            except OSError:
                continue
            stack.extend(children)
        return installed

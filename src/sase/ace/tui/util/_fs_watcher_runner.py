"""Runner mixin: lifecycle and event parsing for ArtifactWatcher."""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import threading
from pathlib import Path

from ._fs_watcher_common import (
    IN_CREATE,
    IN_DELETE_SELF,
    IN_IGNORED,
    IN_ISDIR,
    IN_MOVED_TO,
    IN_MOVE_SELF,
    IN_Q_OVERFLOW,
    is_ignored_watch_name,
    load_libc,
)
from ._fs_watcher_watches import WatcherWatches

log = logging.getLogger(__name__)

# Event header is wd:int32, mask:uint32, cookie:uint32, len:uint32.
_EVENT_HEADER = struct.Struct("iIII")
_EVENT_HEADER_SIZE = _EVENT_HEADER.size


class ArtifactWatcher(WatcherWatches):
    """Watch artifact directories and invoke a callback on changes.

    Construction collects watch paths but does not touch disk; call
    :meth:`start` to spin up the worker thread and :meth:`stop` to tear it
    down.  Events from the worker are delivered to ``on_change`` via
    ``schedule_callback`` (typically Textual's ``call_from_thread``) after
    a short coalesce window so a burst of file activity collapses to one
    reconciliation. A hard deadline still dispatches during sustained
    writes. ``is_relevant`` is the caller-specific consumed-path filter;
    generic ignored names are dropped even when it is omitted.
    """

    def start(self) -> bool:
        """Start the watcher thread.

        Returns ``True`` on success, ``False`` when inotify is unavailable
        or no watch could be installed.  A ``False`` return is non-fatal —
        the caller should fall back to polling.
        """
        libc = load_libc()
        if libc is None:
            log.debug("inotify unsupported on this platform; skipping watcher")
            return False
        IN_NONBLOCK = 0x800
        fd = libc.inotify_init1(IN_NONBLOCK)
        if fd < 0:
            err = ctypes.get_errno()
            log.warning("inotify_init1 failed: errno=%d", err)
            return False
        installed = 0
        for path in self._iter_startup_watch_paths():
            installed += self._add_watch_path(libc, fd, path)
        if installed == 0:
            try:
                os.close(fd)
            except OSError:
                pass
            log.debug("no artifact dirs watchable; falling back to polling")
            return False
        self._fd = fd
        try:
            wake_r, wake_w = os.pipe()
        except OSError:
            log.debug("self-pipe unavailable; watcher stop may wait out select")
            wake_r, wake_w = -1, -1
        else:
            try:
                os.set_blocking(wake_r, False)
                os.set_blocking(wake_w, False)
            except OSError:
                pass
        self._wake_r = wake_r
        self._wake_w = wake_w
        self._thread = threading.Thread(
            target=self._loop,
            name="ace-fs-watcher",
            daemon=True,
        )
        self._thread.start()
        log.debug("inotify watcher started on %d path(s)", installed)
        return True

    def stop(self) -> None:
        """Stop the watcher and release the inotify fd."""
        self._stop_event.set()
        # Wake the worker's ``select()`` at once: closing the inotify fd
        # does not wake ``select()`` on Linux, so the fd stays valid until
        # the thread has been joined and is closed only afterward.
        wake_w = self._wake_w
        if wake_w >= 0:
            try:
                os.write(wake_w, b"\x00")
            except OSError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._thread = None
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        for attr in ("_wake_r", "_wake_w"):
            pipe_fd = getattr(self, attr)
            if pipe_fd >= 0:
                try:
                    os.close(pipe_fd)
                except OSError:
                    pass
                setattr(self, attr, -1)
        with self._watch_lock:
            self._watch_paths_by_wd.clear()
            self._wd_by_path.clear()

    def _loop(self) -> None:
        """Worker loop: read events, coalesce, dispatch to UI."""
        while not self._stop_event.is_set():
            fd = self._fd
            if fd < 0:
                return
            wake_r = self._wake_r
            timeout = self._pending_select_timeout()
            read_fds = [fd] if wake_r < 0 else [fd, wake_r]
            try:
                ready, _, _ = self._select(read_fds, [], [], timeout)
            except (OSError, ValueError):
                # fd was closed under us — shutdown path.
                return
            if wake_r >= 0 and wake_r in ready:
                try:
                    os.read(wake_r, 1024)
                except OSError:
                    pass
                ready = [ready_fd for ready_fd in ready if ready_fd != wake_r]
                if self._stop_event.is_set():
                    return
            if not ready:
                self._stat_select_timeout_wakeups += 1
                self._maybe_flush()
                continue
            if fd in ready:
                self._stat_inotify_readable_wakeups += 1
            try:
                data = os.read(fd, 4096)
            except (BlockingIOError, OSError):
                continue
            changed_paths = self._collect_relevant_events(data)
            if changed_paths:
                self._note_relevant_paths(changed_paths)
            self._maybe_flush()

    def _collect_relevant_events(self, data: bytes) -> set[Path]:
        offset = 0
        paths: set[Path] = set()
        overflow = False
        libc = load_libc()
        while offset + _EVENT_HEADER_SIZE <= len(data):
            wd, mask, _, name_len = _EVENT_HEADER.unpack_from(data, offset)
            offset += _EVENT_HEADER_SIZE
            raw_name = data[offset : offset + name_len].split(b"\0", 1)[0]
            offset += name_len
            self._stat_raw_events += 1
            # ``IN_IGNORED`` arrives without ``self._mask`` bits set after
            # the kernel auto-detaches a watch — handle it regardless so we
            # always reclaim the tracking entry.
            if mask & IN_IGNORED:
                self._remove_watch(libc, self._fd, wd)
                self._stat_ignored_events += 1
                continue
            if mask & IN_Q_OVERFLOW:
                overflow = True
                continue
            if not (mask & self._mask):
                self._stat_rejected_events += 1
                continue
            with self._watch_lock:
                base_path = self._watch_paths_by_wd.get(wd)
            if base_path is None:
                self._stat_rejected_events += 1
                continue
            try:
                name = raw_name.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                name = ""
            event_path = base_path / name if name else base_path
            ignored_name = is_ignored_watch_name(name or event_path.name)
            if (
                libc is not None
                and mask & IN_ISDIR
                and mask & (IN_CREATE | IN_MOVED_TO)
                and not ignored_name
            ):
                self._add_watch_tree(libc, self._fd, event_path)
            if mask & (IN_DELETE_SELF | IN_MOVE_SELF):
                # Drop the bookkeeping entry; the kernel will follow up
                # with ``IN_IGNORED`` to free the wd, but removing the
                # path mapping here keeps the dict bounded immediately.
                self._remove_watch(libc, self._fd, wd)
            if ignored_name or not self._path_is_consumed(event_path):
                self._stat_ignored_events += 1
                continue
            paths.add(event_path)
            self._stat_accepted_events += 1
        if overflow:
            self._stat_accepted_events += 1
            if not paths:
                paths.update(self._paths)
        return paths

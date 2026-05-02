"""Event-driven artifact-directory watcher for the ace TUI.

Phase 5 of sdd/tales/202604/instant_jk_navigation.md (bead sase-u.5). The TUI
historically polled disk every 10 s to discover new agents, status flips,
done.json markers, etc.  This module wakes the UI on actual file-system
events instead, so external changes surface within ~50 ms while the auto-
refresh timer can fall back to a slow safety-net cadence.

The watcher uses Linux inotify directly via ``ctypes`` so we don't add a
runtime dependency. On platforms without inotify the watcher silently
declines to start; callers continue to rely on the polling fallback.

Events from the worker thread are coalesced through a small idle delay
before the UI-thread callback runs so a burst of writes (e.g. a child
agent emitting many JSON files in quick succession) produces exactly one
reconciliation.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import select
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

log = logging.getLogger(__name__)

# inotify constants (from <sys/inotify.h>) — pinned literals so we don't
# need to introspect kernel headers at import time.
_IN_MODIFY = 0x00000002
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200

DEFAULT_EVENT_MASK = (
    _IN_MODIFY
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
)

# Event header is wd:int32, mask:uint32, cookie:uint32, len:uint32.
_EVENT_HEADER = struct.Struct("iIII")
_EVENT_HEADER_SIZE = _EVENT_HEADER.size

DEFAULT_COALESCE_S = 0.05


def _libc() -> ctypes.CDLL | None:
    """Return ``libc`` with inotify symbols, or ``None`` when unavailable."""
    if not sys.platform.startswith("linux"):
        return None
    libc_path = ctypes.util.find_library("c")
    if libc_path is None:
        return None
    try:
        libc = ctypes.CDLL(libc_path, use_errno=True)
    except OSError:
        return None
    if not hasattr(libc, "inotify_init1") or not hasattr(libc, "inotify_add_watch"):
        return None
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    libc.inotify_add_watch.restype = ctypes.c_int
    return libc


class ArtifactWatcher:
    """Watch artifact directories and invoke a callback on changes.

    Construction collects watch paths but does not touch disk; call
    :meth:`start` to spin up the worker thread and :meth:`stop` to tear it
    down.  Events from the worker are delivered to ``on_change`` via
    ``schedule_callback`` (typically Textual's ``call_from_thread``) after
    a short coalesce window so a burst of file activity collapses to one
    reconciliation.
    """

    def __init__(
        self,
        paths: Iterable[Path | str],
        on_change: Callable[[], None],
        schedule_callback: Callable[[Callable[[], None]], object],
        *,
        mask: int = DEFAULT_EVENT_MASK,
        coalesce_s: float = DEFAULT_COALESCE_S,
    ) -> None:
        self._paths: list[Path] = [Path(p) for p in paths]
        self._on_change = on_change
        self._schedule_callback = schedule_callback
        self._mask = mask
        self._coalesce_s = coalesce_s
        self._fd: int = -1
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_event_mono: float = 0.0
        self._lock = threading.Lock()

    def start(self) -> bool:
        """Start the watcher thread.

        Returns ``True`` on success, ``False`` when inotify is unavailable
        or no watch could be installed.  A ``False`` return is non-fatal —
        the caller should fall back to polling.
        """
        libc = _libc()
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
        for path in self._paths:
            try:
                if not path.exists():
                    continue
            except OSError:
                continue
            wd = libc.inotify_add_watch(fd, str(path).encode("utf-8"), self._mask)
            if wd < 0:
                err = ctypes.get_errno()
                log.debug("inotify_add_watch(%s) failed: errno=%d", path, err)
                continue
            installed += 1
        if installed == 0:
            try:
                os.close(fd)
            except OSError:
                pass
            log.debug("no artifact dirs watchable; falling back to polling")
            return False
        self._fd = fd
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
        # Closing the fd unblocks the select() in the worker.
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        """Worker loop: read events, coalesce, dispatch to UI."""
        idle_timeout = 0.5
        while not self._stop_event.is_set():
            fd = self._fd
            if fd < 0:
                return
            # If a pending event is waiting to be flushed, shorten the
            # select timeout so the dispatch runs within the coalesce
            # window once the event burst quiesces.
            with self._lock:
                pending = self._last_event_mono != 0.0
            timeout = self._coalesce_s if pending else idle_timeout
            try:
                ready, _, _ = select.select([fd], [], [], timeout)
            except (OSError, ValueError):
                # fd was closed under us — shutdown path.
                return
            if not ready:
                self._maybe_flush()
                continue
            try:
                data = os.read(fd, 4096)
            except (BlockingIOError, OSError):
                continue
            if not self._has_relevant_event(data):
                continue
            with self._lock:
                self._last_event_mono = time.monotonic()
            self._maybe_flush()

    def _has_relevant_event(self, data: bytes) -> bool:
        offset = 0
        saw = False
        while offset + _EVENT_HEADER_SIZE <= len(data):
            unpacked = _EVENT_HEADER.unpack_from(data, offset)
            mask = unpacked[1]
            name_len = unpacked[3]
            offset += _EVENT_HEADER_SIZE + name_len
            if mask & self._mask:
                saw = True
        return saw

    def _maybe_flush(self) -> None:
        """Dispatch coalesced events to the UI thread once idle."""
        with self._lock:
            last = self._last_event_mono
        if last == 0.0:
            return
        elapsed = time.monotonic() - last
        if elapsed < self._coalesce_s:
            return
        with self._lock:
            if self._last_event_mono == 0.0:
                return
            self._last_event_mono = 0.0
        try:
            self._schedule_callback(self._on_change)
        except RuntimeError:
            # Textual rejects ``call_from_thread`` after the app exits;
            # treat that as a clean shutdown signal.
            self._stop_event.set()
        except Exception:
            log.exception("artifact watcher callback dispatch failed")

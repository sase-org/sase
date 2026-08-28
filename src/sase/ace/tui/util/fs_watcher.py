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
import inspect
import logging
import os
import select
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path

from sase.core.time import local_now

log = logging.getLogger(__name__)
_LIBC_UNSET = object()
_LIBC: ctypes.CDLL | None | object = _LIBC_UNSET

# inotify constants (from <sys/inotify.h>) — pinned literals so we don't
# need to introspect kernel headers at import time.
_IN_MODIFY = 0x00000002
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_IGNORED = 0x00008000
_IN_ISDIR = 0x40000000

DEFAULT_EVENT_MASK = (
    _IN_MODIFY
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
)

# Hard cap on simultaneously-installed inotify watches. Each launched
# agent's artifact tree adds dozens of watches; without a ceiling the
# kernel watch table grows unbounded over a long ACE session.
MAX_INOTIFY_WATCHES = 4096
MAX_STARTUP_ACE_RUN_MONTH_WATCHES = 2
MAX_STARTUP_ACE_RUN_DAY_WATCHES = 14

# Event header is wd:int32, mask:uint32, cookie:uint32, len:uint32.
_EVENT_HEADER = struct.Struct("iIII")
_EVENT_HEADER_SIZE = _EVENT_HEADER.size

DEFAULT_COALESCE_S = 0.05


def live_ace_run_shard_names(now: datetime | None = None) -> tuple[str, str]:
    """Return the live ``YYYYMM`` month and ``DD`` day shard names."""
    current = local_now() if now is None else now
    return current.strftime("%Y%m"), current.strftime("%d")


def iter_future_ace_run_month_dirs(
    workflow_dir: Path,
    *,
    now: datetime | None = None,
) -> Iterator[Path]:
    """Yield existing ace-run month dirs dated after the live month."""
    current_month, _ = live_ace_run_shard_names(now)
    for month_dir in _iter_month_dirs(workflow_dir):
        if month_dir.name > current_month:
            yield month_dir


def iter_startup_ace_run_shard_watch_paths(
    workflow_dir: Path,
    *,
    now: datetime | None = None,
    max_months: int = MAX_STARTUP_ACE_RUN_MONTH_WATCHES,
    max_days: int = MAX_STARTUP_ACE_RUN_DAY_WATCHES,
) -> Iterator[Path]:
    """Yield the month/day shards ACE should watch at startup.

    Future-dated shards are dropped so lexicographic junk cannot consume the
    budget. The live month and today's day shard are always included when they
    exist. Remaining day slots are spent newest-first across the selected
    months rather than letting one month exhaust the budget.
    """
    current_month, current_day = live_ace_run_shard_names(now)
    live_month_dir = workflow_dir / current_month
    live_day_dir = live_month_dir / current_day

    month_dirs = [
        month_dir
        for month_dir in _iter_month_dirs(workflow_dir)
        if month_dir.name <= current_month
    ]
    month_dirs.sort(key=lambda path: path.name, reverse=True)
    selected_months = _force_include_path(
        month_dirs[: max(max_months, 0)],
        live_month_dir,
        key=lambda path: path.name,
        budget=max(max_months, 0),
    )

    day_candidates: list[Path] = []
    for month_dir in selected_months:
        try:
            children = tuple(month_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not _path_is_dir(child) or not _is_day_shard(child.name):
                continue
            if month_dir.name == current_month and child.name > current_day:
                continue
            day_candidates.append(child)
    day_candidates.sort(key=lambda path: (path.parent.name, path.name), reverse=True)
    selected_days = _force_include_path(
        day_candidates[: max(max_days, 0)],
        live_day_dir,
        key=lambda path: (path.parent.name, path.name),
        budget=max(max_days, 0),
    )

    for month_dir in selected_months:
        yield month_dir
        for day_dir in selected_days:
            if day_dir.parent == month_dir:
                yield day_dir


def _iter_month_dirs(workflow_dir: Path) -> tuple[Path, ...]:
    try:
        children = tuple(workflow_dir.iterdir())
    except OSError:
        return ()
    return tuple(
        child
        for child in children
        if _path_is_dir(child) and _is_month_shard(child.name)
    )


def _force_include_path(
    selected: list[Path],
    required: Path,
    *,
    key: Callable[[Path], str | tuple[str, str]],
    budget: int,
) -> list[Path]:
    """Ensure *required* is selected when it exists on disk."""
    if not _path_is_dir(required):
        return selected
    if any(path == required for path in selected):
        return selected
    if budget <= 0:
        chosen = [required]
    elif len(selected) < budget:
        chosen = [*selected, required]
    else:
        chosen = [*selected[:-1], required]
    chosen.sort(key=key, reverse=True)
    return chosen


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _libc() -> ctypes.CDLL | None:
    """Return ``libc`` with inotify symbols, or ``None`` when unavailable."""
    global _LIBC  # noqa: PLW0603
    if _LIBC is not _LIBC_UNSET:
        return _LIBC if isinstance(_LIBC, ctypes.CDLL) else None
    if not sys.platform.startswith("linux"):
        _LIBC = None
        return None
    libc_path = ctypes.util.find_library("c")
    if libc_path is None:
        _LIBC = None
        return None
    try:
        libc = ctypes.CDLL(libc_path, use_errno=True)
    except OSError:
        _LIBC = None
        return None
    if not hasattr(libc, "inotify_init1") or not hasattr(libc, "inotify_add_watch"):
        _LIBC = None
        return None
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    libc.inotify_add_watch.restype = ctypes.c_int
    if hasattr(libc, "inotify_rm_watch"):
        libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        libc.inotify_rm_watch.restype = ctypes.c_int
    _LIBC = libc
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
        on_change: Callable[..., None],
        schedule_callback: Callable[[Callable[[], None]], object],
        *,
        mask: int = DEFAULT_EVENT_MASK,
        coalesce_s: float = DEFAULT_COALESCE_S,
    ) -> None:
        self._paths: list[Path] = [Path(p) for p in paths]
        self._on_change = on_change
        self._on_change_accepts_paths = _callback_accepts_positional(on_change)
        self._schedule_callback = schedule_callback
        self._mask = mask
        self._coalesce_s = coalesce_s
        self._fd: int = -1
        self._watch_paths_by_wd: dict[int, Path] = {}
        self._wd_by_path: dict[str, int] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_event_mono: float = 0.0
        self._pending_paths: set[Path] = set()
        self._lock = threading.Lock()
        self._watch_lock = threading.Lock()
        self._watch_cap_warning_emitted = False

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
        with self._watch_lock:
            self._watch_paths_by_wd.clear()
            self._wd_by_path.clear()

    def ensure_watches(self, paths: Iterable[Path | str]) -> int:
        """Install watches for existing paths that are not already watched.

        Safe to call from the UI thread. Already-watched paths are a cheap
        no-op and do not consume the watch budget. Returns how many new
        watches were installed. A watcher that never started, or has been
        stopped, is a no-op that returns ``0``.
        """
        if self._stop_event.is_set() or self._fd < 0:
            return 0
        libc = _libc()
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
        libc = _libc()
        fd = self._fd
        pruned = 0
        for raw_path in terminal_dirs:
            path = Path(raw_path)
            if not _is_agent_artifact_dir_name(path.name):
                continue
            with self._watch_lock:
                wd = self._wd_by_path.get(_watch_key(path))
            if wd is None:
                continue
            self._remove_watch(libc, fd, wd)
            pruned += 1
        return pruned

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
            changed_paths = self._collect_relevant_events(data)
            if not changed_paths:
                continue
            with self._lock:
                self._last_event_mono = time.monotonic()
                self._pending_paths.update(changed_paths)
            self._maybe_flush()

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
            if _is_agent_artifact_dir_name(current.name):
                continue
            try:
                children = tuple(
                    child for child in current.iterdir() if _path_is_dir(child)
                )
            except OSError:
                continue
            stack.extend(children)
        return installed

    def _collect_relevant_events(self, data: bytes) -> set[Path]:
        offset = 0
        paths: set[Path] = set()
        libc = _libc()
        while offset + _EVENT_HEADER_SIZE <= len(data):
            wd, mask, _, name_len = _EVENT_HEADER.unpack_from(data, offset)
            offset += _EVENT_HEADER_SIZE
            raw_name = data[offset : offset + name_len].split(b"\0", 1)[0]
            offset += name_len
            # ``IN_IGNORED`` arrives without ``self._mask`` bits set after
            # the kernel auto-detaches a watch — handle it regardless so we
            # always reclaim the tracking entry.
            if mask & _IN_IGNORED:
                self._remove_watch(libc, self._fd, wd)
                continue
            if mask & self._mask:
                with self._watch_lock:
                    base_path = self._watch_paths_by_wd.get(wd)
                if base_path is None:
                    continue
                try:
                    name = raw_name.decode("utf-8", errors="replace")
                except UnicodeDecodeError:
                    name = ""
                event_path = base_path / name if name else base_path
                paths.add(event_path)
                if (
                    libc is not None
                    and mask & _IN_ISDIR
                    and mask & (_IN_CREATE | _IN_MOVED_TO)
                ):
                    self._add_watch_tree(libc, self._fd, event_path)
                if mask & (_IN_DELETE_SELF | _IN_MOVE_SELF):
                    # Drop the bookkeeping entry; the kernel will follow up
                    # with ``IN_IGNORED`` to free the wd, but removing the
                    # path mapping here keeps the dict bounded immediately.
                    self._remove_watch(libc, self._fd, wd)
        return paths

    def _maybe_flush(self) -> None:
        """Dispatch coalesced events to the UI thread once idle."""
        if self._stop_event.is_set():
            return
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
            changed_paths = tuple(sorted(self._pending_paths))
            self._pending_paths.clear()
        if self._stop_event.is_set():
            return
        try:

            def dispatch() -> None:
                self._dispatch_change(changed_paths)

            self._schedule_callback(dispatch)
        except RuntimeError:
            # Textual rejects ``call_from_thread`` after the app exits;
            # treat that as a clean shutdown signal.
            self._stop_event.set()
        except Exception:
            log.exception("artifact watcher callback dispatch failed")

    def _dispatch_change(self, changed_paths: tuple[Path, ...]) -> None:
        if self._on_change_accepts_paths:
            self._on_change(changed_paths)
        else:
            self._on_change()


def _callback_accepts_positional(callback: Callable[..., object]) -> bool:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


def _is_month_shard(name: str) -> bool:
    return len(name) == 6 and name.isdigit()


def _is_day_shard(name: str) -> bool:
    if len(name) != 2 or not name.isdigit():
        return False
    return 1 <= int(name) <= 31


def _is_agent_artifact_dir_name(name: str) -> bool:
    return len(name) == 14 and name.isdigit()


def _watch_key(path: Path) -> str:
    return str(path)

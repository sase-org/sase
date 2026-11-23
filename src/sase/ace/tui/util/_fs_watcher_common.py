"""Shared inotify and ignore-policy helpers for the fs_watcher split.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

# inotify constants (from <sys/inotify.h>) — pinned literals so we don't
# need to introspect kernel headers at import time. Public names because
# both the core defaults and the runner event parser need them.
IN_MODIFY = 0x00000002
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000

_LIBC_UNSET = object()
_LIBC: ctypes.CDLL | None | object = _LIBC_UNSET

_IGNORED_WATCH_NAMES = frozenset(
    {
        ".DS_Store",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "4913",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
_IGNORED_WATCH_SUFFIXES = (
    ".bak",
    ".pyc",
    ".pyo",
    ".swn",
    ".swo",
    ".swp",
    ".swx",
    ".temp",
    ".tmp",
)


def is_ignored_watch_name(name: str) -> bool:
    """Return True for names no TUI consumer reads.

    Applied before a path is armed for dispatch and before a newly created
    directory grows the watch table. Empty names (the watched path itself)
    stay relevant so deletion/rename of a watch root still surfaces.
    """
    if not name:
        return False
    if name in _IGNORED_WATCH_NAMES:
        return True
    if name.endswith("~"):
        return True
    if name.startswith(".#"):
        return True
    if name.startswith("#") and name.endswith("#"):
        return True
    if name.endswith(("-journal", "-shm", "-wal")):
        return True
    lowered = name.lower()
    return lowered.endswith(_IGNORED_WATCH_SUFFIXES)


def load_libc() -> ctypes.CDLL | None:
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

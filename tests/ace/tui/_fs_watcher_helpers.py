"""Shared helpers for ArtifactWatcher test modules.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

import pytest

from sase.ace.tui.util._fs_watcher_common import load_libc

__all__ = [
    "LINUX_ONLY",
    "schedule_inline",
    "wait",
]


LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux") or load_libc() is None,
    reason="inotify is Linux-only and not available in this environment",
)


def wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    return predicate()


def schedule_inline(cb: Callable[[], None]) -> None:
    cb()

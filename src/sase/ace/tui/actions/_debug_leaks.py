"""Optional in-memory leak instrumentation gated by ``SASE_ACE_DEBUG_LEAKS``.

The plan in ``sdd/tales/202605/ace_tui_slowdown.md`` (D1/D2) needs a cheap,
opt-in probe that reports the sizes of the structures most likely to
grow unbounded over a long ACE session. Both surfaces:

* a periodic snapshot fired from the existing auto-refresh tick — so
  we don't add a new timer; and
* a one-shot keybind (``ctrl+shift+d``) that dumps the same data
  synchronously and surfaces the headline counts as a Textual
  notification.

Everything is no-op unless ``SASE_ACE_DEBUG_LEAKS=1`` is set in the
environment when ACE starts.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_ENV_VAR = "SASE_ACE_DEBUG_LEAKS"


def debug_leaks_enabled() -> bool:
    """Return ``True`` when the leak-snapshot instrumentation is enabled."""
    return os.environ.get(_ENV_VAR) == "1"


def _snapshot_pending_asyncio_tasks() -> int:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0
    try:
        return sum(1 for t in asyncio.all_tasks(loop) if not t.done())
    except RuntimeError:
        return 0


def _count_open_fds() -> int | None:
    """Return /proc/self/fd entry count; ``None`` when unavailable."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def _collect_leak_snapshot(app: Any) -> dict[str, int | None]:
    """Return current sizes of the structures known to grow unbounded."""
    cache = getattr(app, "_artifact_file_page_cache", None)
    artifact_cache_len = len(cache) if cache is not None else 0

    watcher = getattr(app, "_fs_watcher", None)
    watch_count: int | None
    if watcher is not None:
        wd_map = getattr(watcher, "_watch_paths_by_wd", None)
        watch_count = len(wd_map) if wd_map is not None else None
    else:
        watch_count = None

    dismissed_objects = getattr(app, "_dismissed_agent_objects", None)
    dismissed_len = len(dismissed_objects) if dismissed_objects is not None else 0

    agents_with_children = getattr(app, "_agents_with_children", None)
    agents_len = len(agents_with_children) if agents_with_children is not None else 0

    return {
        "artifact_page_cache": artifact_cache_len,
        "fs_watcher_watches": watch_count,
        "dismissed_agent_objects": dismissed_len,
        "agents_with_children": agents_len,
        "pending_asyncio_tasks": _snapshot_pending_asyncio_tasks(),
        "open_fds": _count_open_fds(),
    }


def log_leak_snapshot(app: Any, *, source: str) -> dict[str, int | None]:
    """Log the leak snapshot at INFO and return it for caller use."""
    snapshot = _collect_leak_snapshot(app)
    log.info(
        "ace_debug_leaks source=%s artifact_page_cache=%s fs_watcher_watches=%s "
        "dismissed_agent_objects=%s agents_with_children=%s "
        "pending_asyncio_tasks=%s open_fds=%s",
        source,
        snapshot["artifact_page_cache"],
        snapshot["fs_watcher_watches"],
        snapshot["dismissed_agent_objects"],
        snapshot["agents_with_children"],
        snapshot["pending_asyncio_tasks"],
        snapshot["open_fds"],
    )
    return snapshot

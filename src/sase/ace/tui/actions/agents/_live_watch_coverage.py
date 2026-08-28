"""Re-arm inotify coverage for in-flight agent artifact directories.

Startup watches are shard-bounded and never include pre-existing 14-digit
agent directories. After each agents load, install watches for live rows
and prune watches for loaded terminal rows so coverage self-heals after
ACE start, ``os.execvp`` hot-restart, or a missed ``IN_CREATE``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...models.agent_family_members import agent_row_is_in_flight

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)

MAX_LIVE_AGENT_WATCHES = 256

_live_watch_cap_warning_emitted = False


def rearm_live_agent_watch_coverage(app: Any) -> None:
    """Ensure live artifact dirs are watched and prune loaded terminal dirs.

    Uses the already-loaded roster and ``get_artifacts_dir()`` only; it
    must not add other disk lookups. No-ops when the watcher is absent.
    """
    watcher = getattr(app, "_fs_watcher", None)
    if watcher is None:
        return
    ensure_watches = getattr(watcher, "ensure_watches", None)
    prune_watches = getattr(watcher, "prune_agent_dir_watches", None)
    if not callable(ensure_watches) and not callable(prune_watches):
        return

    in_flight_by_dir: dict[str, tuple[tuple[str, str], Path]] = {}
    terminal_by_dir: dict[str, Path] = {}
    for agent in getattr(app, "_agents_with_children", None) or ():
        artifact_dir = _agent_watch_dir(agent)
        if artifact_dir is None:
            continue
        key = str(artifact_dir)
        if agent_row_is_in_flight(agent):
            in_flight_by_dir[key] = (_live_watch_sort_key(agent), artifact_dir)
            terminal_by_dir.pop(key, None)
        elif key not in in_flight_by_dir:
            terminal_by_dir[key] = artifact_dir

    ensure_paths = [
        path
        for _, path in sorted(
            in_flight_by_dir.values(),
            key=lambda item: item[0],
            reverse=True,
        )
    ]
    global _live_watch_cap_warning_emitted  # noqa: PLW0603
    if len(ensure_paths) > MAX_LIVE_AGENT_WATCHES:
        if not _live_watch_cap_warning_emitted:
            log.warning(
                "live agent watch cap (%d) reached; newest in-flight dirs kept",
                MAX_LIVE_AGENT_WATCHES,
            )
            _live_watch_cap_warning_emitted = True
        ensure_paths = ensure_paths[:MAX_LIVE_AGENT_WATCHES]

    if callable(ensure_watches) and ensure_paths:
        ensure_watches(ensure_paths)
    if callable(prune_watches) and terminal_by_dir:
        prune_watches(terminal_by_dir.values())


def _agent_watch_dir(agent: Agent) -> Path | None:
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None
    try:
        artifacts_dir = get_artifacts_dir()
    except Exception:  # noqa: BLE001 - coverage must never fail an agents apply
        return None
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    return Path(artifacts_dir)


def _live_watch_sort_key(agent: Agent) -> tuple[str, str]:
    start = getattr(agent, "start_time", None)
    start_key = start.strftime("%Y%m%d%H%M%S") if start is not None else ""
    return (start_key, getattr(agent, "raw_suffix", None) or "")

"""Loader for per-agent ``sase memory read`` audit events."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.main.init_memory.config import project_memory_name
from sase.memory.read_log import (
    MemoryReadEvent,
    memory_read_log_path,
    read_memory_read_events,
)

MAX_KEPT_READS = 50
_MIN_REREAD_INTERVAL_S = 0.5


@dataclass
class _MemoryReadsCacheEntry:
    events: tuple[MemoryReadEvent, ...]
    log_mtime_ns: int
    last_read_monotonic: float


_memory_reads_cache: dict[tuple[str, str], _MemoryReadsCacheEntry] = {}


def _project_name_for_agent(agent: Agent) -> str | None:
    workspace_dir = agent.workspace_dir
    if workspace_dir:
        try:
            return project_memory_name(Path(workspace_dir))
        except Exception:
            pass
    try:
        return project_memory_name(Path.cwd())
    except Exception:
        return None


def _cache_key(project: str, agent: Agent) -> tuple[str, str]:
    from sase.ace.tui.widgets.tools_panel import get_cache_key

    return (project, get_cache_key(agent))


def _normalize_dir(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return os.path.realpath(value)
    except (OSError, ValueError):
        return value


def _filter_events_for_agent(
    events: tuple[MemoryReadEvent, ...], agent: Agent
) -> tuple[MemoryReadEvent, ...]:
    artifacts_dir_raw = agent.get_artifacts_dir()
    agent_artifacts_dir = _normalize_dir(artifacts_dir_raw)
    agent_name = agent.agent_name

    matches: list[MemoryReadEvent] = []
    for event in events:
        event_artifacts_dir = _normalize_dir(event.artifacts_dir)
        if event_artifacts_dir is not None and agent_artifacts_dir is not None:
            if event_artifacts_dir == agent_artifacts_dir:
                matches.append(event)
            continue
        # Fallback: match by agent_name when the event has no artifacts_dir.
        if (
            event_artifacts_dir is None
            and agent_name
            and event.agent_name == agent_name
        ):
            matches.append(event)
    return tuple(matches)


def _stat_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def load_memory_reads_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_READS
) -> tuple[MemoryReadEvent, ...]:
    """Return memory-read events attributed to ``agent``, newest first.

    Uses an mtime-keyed cache + throttle to make repeated calls cheap on the
    j/k navigation hot path.
    """
    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = memory_read_log_path(project)
    now = time.monotonic()
    key = _cache_key(project, agent)
    cached = _memory_reads_cache.get(key)
    current_mtime = _stat_mtime_ns(log_path)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_mtime == cached.log_mtime_ns:
            return cached.events[:limit]

    all_events = read_memory_read_events(project=project)
    filtered = _filter_events_for_agent(all_events, agent)
    ordered = tuple(sorted(filtered, key=lambda event: event.timestamp, reverse=True))
    capped = ordered[:MAX_KEPT_READS]
    _memory_reads_cache[key] = _MemoryReadsCacheEntry(
        events=capped,
        log_mtime_ns=current_mtime,
        last_read_monotonic=now,
    )
    return capped[:limit]

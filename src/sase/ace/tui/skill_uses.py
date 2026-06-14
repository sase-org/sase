"""Loader for per-agent ``sase skills log`` audit events."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.main.init_memory.config import project_memory_name
from sase.skills.use_log import (
    SkillUseEvent,
    read_skill_use_events,
    skill_use_log_path,
)

MAX_KEPT_SKILL_USES = 50
_MIN_REREAD_INTERVAL_S = 0.5


@dataclass
class _SkillUsesCacheEntry:
    events: tuple[SkillUseEvent, ...]
    log_mtime_ns: int
    last_read_monotonic: float


_skill_uses_cache: dict[tuple[str, str], _SkillUsesCacheEntry] = {}


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
    events: tuple[SkillUseEvent, ...], agent: Agent
) -> tuple[SkillUseEvent, ...]:
    artifacts_dir_raw = agent.get_artifacts_dir()
    agent_artifacts_dir = _normalize_dir(artifacts_dir_raw)
    agent_name = agent.agent_name

    matches: list[SkillUseEvent] = []
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


def load_skill_uses_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_SKILL_USES
) -> tuple[SkillUseEvent, ...]:
    """Return skill-use events attributed to ``agent``, newest first.

    Uses an mtime-keyed cache + throttle to make repeated calls cheap on the
    j/k navigation hot path.
    """
    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = skill_use_log_path(project)
    now = time.monotonic()
    key = _cache_key(project, agent)
    cached = _skill_uses_cache.get(key)
    current_mtime = _stat_mtime_ns(log_path)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_mtime == cached.log_mtime_ns:
            return cached.events[:limit]

    all_events = read_skill_use_events(project=project)
    filtered = _filter_events_for_agent(all_events, agent)
    ordered = tuple(sorted(filtered, key=lambda event: event.timestamp, reverse=True))
    capped = ordered[:MAX_KEPT_SKILL_USES]
    _skill_uses_cache[key] = _SkillUsesCacheEntry(
        events=capped,
        log_mtime_ns=current_mtime,
        last_read_monotonic=now,
    )
    return capped[:limit]

"""Loader for per-agent ``sase skill use`` audit events."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.util.normalized_dirs import (
    normalize_dir as _normalize_dir,
)
from sase.main.init_memory.config import project_memory_name
from sase.skills.use_log import (
    SkillUseEvent,
    read_skill_use_events,
    skill_use_log_path,
)

MAX_KEPT_SKILL_USES = 50
_MIN_REREAD_INTERVAL_S = 0.5
_MAX_SNAPSHOT_CACHE_PROJECTS = 8
_LogStat = tuple[int, int]


@dataclass(frozen=True)
class SkillUseDisplayEvent:
    """A skill-use event paired with an optional family role label.

    ``agent_label`` is ``None`` for ordinary (single-member) rows so the
    existing per-agent visual shape is preserved; family rows set it to the
    producing member's compact role label (e.g. ``q``, ``commit``).
    """

    event: SkillUseEvent
    agent_label: str | None = None


@dataclass
class _SkillUsesCacheEntry:
    events: tuple[SkillUseEvent, ...]
    log_mtime_ns: int
    log_size: int
    last_read_monotonic: float


@dataclass
class _SkillUsesContextCacheEntry:
    events: tuple[SkillUseDisplayEvent, ...]
    log_mtime_ns: int
    log_size: int
    last_read_monotonic: float


@dataclass
class _SkillUsesSnapshotCacheEntry:
    events: tuple[SkillUseEvent, ...]
    log_mtime_ns: int
    log_size: int
    last_read_monotonic: float


_skill_uses_cache: dict[tuple[str, str], _SkillUsesCacheEntry] = {}
_skill_uses_context_cache: dict[
    tuple[str, tuple[str, ...]], _SkillUsesContextCacheEntry
] = {}
_skill_uses_snapshot_cache: OrderedDict[str, _SkillUsesSnapshotCacheEntry] = (
    OrderedDict()
)


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
    from sase.ace.tui.tools.cache import get_cache_key

    return (project, get_cache_key(agent))


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


def _stat_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _log_stat(path: Path) -> _LogStat:
    return (_stat_mtime_ns(path), _stat_size(path))


def _cache_entry_stat(
    entry: _SkillUsesCacheEntry | _SkillUsesContextCacheEntry,
) -> _LogStat:
    return (entry.log_mtime_ns, entry.log_size)


def _load_skill_use_events_snapshot(
    project: str,
    *,
    log_path: Path,
    now: float,
    current_stat: _LogStat,
) -> tuple[tuple[SkillUseEvent, ...], _LogStat]:
    cached = _skill_uses_snapshot_cache.get(project)
    if cached is not None:
        cached_stat = (cached.log_mtime_ns, cached.log_size)
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == cached_stat:
            _skill_uses_snapshot_cache.move_to_end(project)
            return cached.events, cached_stat

    events = read_skill_use_events(project=project)
    entry = _SkillUsesSnapshotCacheEntry(
        events=events,
        log_mtime_ns=current_stat[0],
        log_size=current_stat[1],
        last_read_monotonic=now,
    )
    _skill_uses_snapshot_cache[project] = entry
    _skill_uses_snapshot_cache.move_to_end(project)
    while len(_skill_uses_snapshot_cache) > _MAX_SNAPSHOT_CACHE_PROJECTS:
        _skill_uses_snapshot_cache.popitem(last=False)
    return events, current_stat


def _load_skill_uses_for_agent(
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
    current_stat = _log_stat(log_path)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == _cache_entry_stat(cached):
            return cached.events[:limit]

    all_events, snapshot_stat = _load_skill_use_events_snapshot(
        project,
        log_path=log_path,
        now=now,
        current_stat=current_stat,
    )
    filtered = _filter_events_for_agent(all_events, agent)
    ordered = tuple(sorted(filtered, key=lambda event: event.timestamp, reverse=True))
    capped = ordered[:MAX_KEPT_SKILL_USES]
    _skill_uses_cache[key] = _SkillUsesCacheEntry(
        events=capped,
        log_mtime_ns=snapshot_stat[0],
        log_size=snapshot_stat[1],
        last_read_monotonic=now,
    )
    return capped[:limit]


def load_skill_uses_for_agent_context(
    agent: Agent, *, limit: int = MAX_KEPT_SKILL_USES
) -> tuple[SkillUseDisplayEvent, ...]:
    """Return display skill-uses for an agent-family context, newest first.

    For an ordinary row with no follow-up family members this delegates to
    :func:`_load_skill_uses_for_agent` and wraps each event with no label,
    preserving the single-agent visual shape. For a family row it reads the
    log once, attributes each event to a member, de-duplicates by event id,
    sorts newest first, caps to ``MAX_KEPT_SKILL_USES``, and labels each kept
    event with its producer's compact role.
    """
    from sase.ace.tui.agent_context_members import (
        build_context_members,
        context_cache_key,
        match_event_label,
    )

    members = build_context_members(agent)
    if len(members) <= 1:
        events = _load_skill_uses_for_agent(agent, limit=limit)
        return tuple(SkillUseDisplayEvent(event=event) for event in events)

    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = skill_use_log_path(project)
    now = time.monotonic()
    key = (project, context_cache_key(members))
    cached = _skill_uses_context_cache.get(key)
    current_stat = _log_stat(log_path)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == _cache_entry_stat(cached):
            return cached.events[:limit]

    all_events, snapshot_stat = _load_skill_use_events_snapshot(
        project,
        log_path=log_path,
        now=now,
        current_stat=current_stat,
    )
    matched: list[SkillUseDisplayEvent] = []
    seen_ids: set[str] = set()
    for event in all_events:
        if event.id in seen_ids:
            continue
        label = match_event_label(
            members,
            artifacts_dir=event.artifacts_dir,
            agent_name=event.agent_name,
        )
        if label is None:
            continue
        seen_ids.add(event.id)
        matched.append(SkillUseDisplayEvent(event=event, agent_label=label))

    ordered = tuple(
        sorted(matched, key=lambda item: item.event.timestamp, reverse=True)
    )
    capped = ordered[:MAX_KEPT_SKILL_USES]
    _skill_uses_context_cache[key] = _SkillUsesContextCacheEntry(
        events=capped,
        log_mtime_ns=snapshot_stat[0],
        log_size=snapshot_stat[1],
        last_read_monotonic=now,
    )
    return capped[:limit]

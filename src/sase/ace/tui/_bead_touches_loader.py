"""Per-agent bead-touch loader with mtime-keyed caches.

Reads the touch index file only; it never refreshes it. Refresh runs at
the three off-hot-path sites owned by the host-refresh phase
(post-mutation, post-sync, lumberjack tick), so a stale index returns
stale answers here rather than paying for freshness on the panel's
clock. A missing, truncated, or unparseable index is a cache miss that
returns no rows, never an error.

The legacy, no-longer-written ``bead_views.jsonl`` log is folded in
behind the durable index rows as ``viewed``-only synthetic touches.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui._bead_touches_shared import (
    BeadTouchDisplayEvent,
    parse_moment,
)
from sase.ace.tui.models.agent import Agent
from sase.bead.bead_views import (
    BeadViewEvent,
    bead_views_log_path,
    read_bead_view_events,
    view_touches_for_agent,
    views_to_touches,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    globalize_owned_agent_name,
)
from sase.core.bead_touch_index_facade import (
    BeadTouch,
    BeadTouchQuery,
    merge_view_touches,
    query_touch_index,
    touch_index_path,
    touch_matches_agent,
    touches_for_agent,
)
from sase.main.init_memory.config import project_memory_name

MAX_KEPT_TOUCHES = 50
_MIN_REREAD_INTERVAL_S = 0.5
_MAX_SNAPSHOT_CACHE_PROJECTS = 8
_IndexStat = tuple[int, int]


@dataclass
class _BeadTouchesCacheEntry:
    events: tuple[BeadTouchDisplayEvent, ...]
    index_mtime_ns: int
    index_size: int
    views_mtime_ns: int = 0
    views_size: int = 0
    last_read_monotonic: float = 0.0


@dataclass
class _BeadTouchesContextCacheEntry:
    events: tuple[BeadTouchDisplayEvent, ...]
    index_mtime_ns: int
    index_size: int
    views_mtime_ns: int = 0
    views_size: int = 0
    last_read_monotonic: float = 0.0


@dataclass
class _BeadTouchesSnapshotCacheEntry:
    touches: tuple[BeadTouch, ...]
    index_mtime_ns: int
    index_size: int
    last_read_monotonic: float


@dataclass
class _BeadViewsSnapshotCacheEntry:
    events: tuple[BeadViewEvent, ...]
    views_mtime_ns: int
    views_size: int
    last_read_monotonic: float


_bead_touches_cache: dict[tuple[str, str], _BeadTouchesCacheEntry] = {}
_bead_touches_context_cache: dict[
    tuple[str, tuple[str, ...]], _BeadTouchesContextCacheEntry
] = {}
_bead_touches_snapshot_cache: OrderedDict[str, _BeadTouchesSnapshotCacheEntry] = (
    OrderedDict()
)
_bead_views_snapshot_cache: OrderedDict[str, _BeadViewsSnapshotCacheEntry] = (
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
    from sase.ace.tui.llm_calls.cache import get_cache_key

    return (project, get_cache_key(agent))


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


def _index_stat(path: Path) -> _IndexStat:
    return (_stat_mtime_ns(path), _stat_size(path))


def _cache_entry_stat(
    entry: _BeadTouchesCacheEntry | _BeadTouchesContextCacheEntry,
) -> tuple[int, int, int, int]:
    return (
        entry.index_mtime_ns,
        entry.index_size,
        entry.views_mtime_ns,
        entry.views_size,
    )


def _touch_sort_key(touch: BeadTouch) -> tuple[float, str]:
    moment = parse_moment(touch.last_at)
    return (moment.timestamp() if moment is not None else float("-inf"), touch.bead_id)


def _member_match_params(
    agent_name: str | None,
    identity: AgentIdentitySnapshot,
) -> tuple[str, str | None]:
    """Return ``(globalized_name, local_name)`` for one context member."""
    local = (agent_name or "").strip()
    if not local:
        return ("", None)
    try:
        return (globalize_owned_agent_name(local, identity), local)
    except Exception:
        return (local, local)


def _globalized_name_for_agent(
    agent: Agent, identity: AgentIdentitySnapshot
) -> tuple[str, str | None]:
    return _member_match_params(
        agent.agent_name or agent.presented_agent_name, identity
    )


def _load_touch_index_snapshot(
    project: str,
    *,
    index_path: Path,
    now: float,
    current_stat: _IndexStat,
) -> tuple[tuple[BeadTouch, ...], _IndexStat] | None:
    """Return cached-or-fresh touches, or ``None`` when the query failed.

    A failed query is never cached: the next poll retries instead of
    sticking an error-shaped empty answer to an unchanged mtime.
    """
    cached = _bead_touches_snapshot_cache.get(project)
    if cached is not None:
        cached_stat = (cached.index_mtime_ns, cached.index_size)
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == cached_stat:
            _bead_touches_snapshot_cache.move_to_end(project)
            return cached.touches, cached_stat

    try:
        query: BeadTouchQuery = query_touch_index(index_path)
    except Exception:
        return None
    touches = query.touches
    entry = _BeadTouchesSnapshotCacheEntry(
        touches=touches,
        index_mtime_ns=current_stat[0],
        index_size=current_stat[1],
        last_read_monotonic=now,
    )
    _bead_touches_snapshot_cache[project] = entry
    _bead_touches_snapshot_cache.move_to_end(project)
    while len(_bead_touches_snapshot_cache) > _MAX_SNAPSHOT_CACHE_PROJECTS:
        _bead_touches_snapshot_cache.popitem(last=False)
    return touches, current_stat


def _load_view_snapshot(
    project: str,
    *,
    views_path: Path,
    now: float,
    current_stat: _IndexStat,
) -> tuple[tuple[BeadViewEvent, ...], _IndexStat]:
    """Return cached-or-fresh view events with their file stat.

    The views log is append-only and small; a read failure (or an
    unresolvable path upstream) degrades to no views rather than an error,
    so a missing log simply contributes no ``viewed`` rows.
    """
    cached = _bead_views_snapshot_cache.get(project)
    if cached is not None:
        cached_stat = (cached.views_mtime_ns, cached.views_size)
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == cached_stat:
            _bead_views_snapshot_cache.move_to_end(project)
            return cached.events, cached_stat

    try:
        events = read_bead_view_events(log_path=views_path)
    except Exception:
        return (), current_stat
    entry = _BeadViewsSnapshotCacheEntry(
        events=events,
        views_mtime_ns=current_stat[0],
        views_size=current_stat[1],
        last_read_monotonic=now,
    )
    _bead_views_snapshot_cache[project] = entry
    _bead_views_snapshot_cache.move_to_end(project)
    while len(_bead_views_snapshot_cache) > _MAX_SNAPSHOT_CACHE_PROJECTS:
        _bead_views_snapshot_cache.popitem(last=False)
    return events, current_stat


def _snapshot_for_agent(
    agent: Agent,
) -> (
    tuple[
        str, tuple[BeadTouch, ...], tuple[BeadViewEvent, ...], tuple[int, int, int, int]
    ]
    | None
):
    """Resolve the project, combined stat, touches, and raw view events.

    View events stay unfiltered here: the per-agent loader attributes them
    to one agent while the session loader attributes them per member, both
    through the facade's shared matcher.
    """
    project = _project_name_for_agent(agent)
    if project is None:
        return None
    try:
        index_path = touch_index_path(project)
    except Exception:
        return None
    now = time.monotonic()
    current_stat = _index_stat(index_path)
    snapshot = _load_touch_index_snapshot(
        project,
        index_path=index_path,
        now=now,
        current_stat=current_stat,
    )
    if snapshot is None:
        return None
    try:
        views_path = bead_views_log_path(project)
    except Exception:
        index_stat = snapshot[1]
        return project, snapshot[0], (), (*index_stat, 0, 0)
    views_stat = _index_stat(views_path)
    view_snapshot = _load_view_snapshot(
        project,
        views_path=views_path,
        now=now,
        current_stat=views_stat,
    )
    index_stat = snapshot[1]
    return (
        project,
        snapshot[0],
        view_snapshot[0],
        (*index_stat, *view_snapshot[1]),
    )


def _load_bead_touches_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_TOUCHES
) -> tuple[BeadTouchDisplayEvent, ...]:
    """Return indexed touches attributed to ``agent``, newest first.

    Uses an mtime-keyed cache + throttle to make repeated calls cheap on the
    j/k navigation hot path. Never raises: any failure is an empty answer.
    """
    try:
        return _load_bead_touches_for_agent_inner(agent, limit=limit)
    except Exception:
        return ()


def _load_bead_touches_for_agent_inner(
    agent: Agent, *, limit: int
) -> tuple[BeadTouchDisplayEvent, ...]:
    resolved = _snapshot_for_agent(agent)
    if resolved is None:
        return ()
    project, all_touches, view_events, _snapshot_stat = resolved

    now = time.monotonic()
    key = _cache_key(project, agent)
    cached = _bead_touches_cache.get(key)
    current_stat = _snapshot_stat

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == _cache_entry_stat(cached):
            return cached.events[:limit]

    identity = AgentIdentitySnapshot.current()
    globalized_name, local_name = _globalized_name_for_agent(agent, identity)
    filtered = touches_for_agent(
        all_touches,
        globalized_name=globalized_name,
        local_name=local_name,
        identity=identity,
    )
    view_hits = view_touches_for_agent(
        view_events,
        globalized_name=globalized_name,
        local_name=local_name,
        identity=identity,
    )
    ordered = sorted(
        merge_view_touches(filtered, view_hits), key=_touch_sort_key, reverse=True
    )
    capped = tuple(
        BeadTouchDisplayEvent(touch=touch) for touch in ordered[:MAX_KEPT_TOUCHES]
    )
    _bead_touches_cache[key] = _BeadTouchesCacheEntry(
        events=capped,
        index_mtime_ns=current_stat[0],
        index_size=current_stat[1],
        views_mtime_ns=current_stat[2],
        views_size=current_stat[3],
        last_read_monotonic=now,
    )
    return capped[:limit]


def load_bead_touches_for_agent_context(
    agent: Agent, *, limit: int = MAX_KEPT_TOUCHES
) -> tuple[BeadTouchDisplayEvent, ...]:
    """Return display bead-touches for an agent-session context, newest first.

    For an ordinary row with no follow-up session members this delegates to
    the per-agent loader and wraps each touch with no label, preserving the
    single-agent shape. For a session row it reads the index once, attributes
    each touch to the first member whose identity matches its actor, sorts
    newest first, caps to ``MAX_KEPT_TOUCHES``, and labels each kept touch
    with its producer's compact role. Touches carry only an actor string
    (no artifacts dir), so attribution is name-based through the facade's
    shared matcher. Never raises.
    """
    try:
        return _load_bead_touches_for_agent_context_inner(agent, limit=limit)
    except Exception:
        return ()


def _load_bead_touches_for_agent_context_inner(
    agent: Agent, *, limit: int
) -> tuple[BeadTouchDisplayEvent, ...]:
    from sase.ace.tui.agent_context_members import (
        build_context_members,
        context_cache_key,
    )

    members = build_context_members(agent)
    if len(members) <= 1:
        return _load_bead_touches_for_agent(agent, limit=limit)

    resolved = _snapshot_for_agent(agent)
    if resolved is None:
        return ()
    project, all_touches, view_events, _snapshot_stat = resolved

    now = time.monotonic()
    key = (project, context_cache_key(members))
    cached = _bead_touches_context_cache.get(key)
    current_stat = _snapshot_stat

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_stat == _cache_entry_stat(cached):
            return cached.events[:limit]

    identity = AgentIdentitySnapshot.current()
    matchers = [
        (member.label, *_member_match_params(member.agent_name, identity))
        for member in members
    ]
    matched: list[BeadTouchDisplayEvent] = []
    for touch in all_touches:
        for label, globalized_name, local_name in matchers:
            if touch_matches_agent(
                touch.actor,
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            ):
                matched.append(BeadTouchDisplayEvent(touch=touch, agent_label=label))
                break

    view_rows = views_to_touches(view_events)
    for touch in view_rows:
        for label, globalized_name, local_name in matchers:
            if touch_matches_agent(
                touch.actor,
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            ):
                matched.append(BeadTouchDisplayEvent(touch=touch, agent_label=label))
                break

    matched.sort(key=lambda item: _touch_sort_key(item.touch), reverse=True)
    capped = tuple(matched[:MAX_KEPT_TOUCHES])
    _bead_touches_context_cache[key] = _BeadTouchesContextCacheEntry(
        events=capped,
        index_mtime_ns=current_stat[0],
        index_size=current_stat[1],
        views_mtime_ns=current_stat[2],
        views_size=current_stat[3],
        last_read_monotonic=now,
    )
    return capped[:limit]

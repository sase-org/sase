"""Loader for per-agent bead touches from the touch index.

Modeled directly on :mod:`sase.ace.tui.artifact_reads`: a frozen
display-event dataclass, an mtime-and-size keyed cache with the same
``_MIN_REREAD_INTERVAL_S`` throttle, a bounded snapshot cache across
projects, and a per-agent loader plus an agent-family context loader that
carries the member role label.

The loader reads the index file only; it never refreshes it. Refresh runs
at the three off-hot-path sites owned by the host-refresh phase
(post-mutation, post-sync, lumberjack tick), so a stale index returns stale
answers here rather than paying for freshness on the panel's clock. A
missing, truncated, or unparseable index is a cache miss that returns no
rows, never an error.

The machine-local ``bead_views.jsonl`` log (one row per agent-attributed
``sase bead show``) is folded in behind the durable index rows as
``viewed``-only synthetic touches, so a bead an agent only peeked at still
surfaces, ranked by its newest view, with the weakest glyph and no
promotion to ``read``. The views file is small, append-only, and cached by
its own mtime-and-size stat under the same throttle, keeping the j/k
navigation hot path to stat calls on a cache hit.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent

MAX_KEPT_TOUCHES = 50
_MIN_REREAD_INTERVAL_S = 0.5
_MAX_SNAPSHOT_CACHE_PROJECTS = 8
_IndexStat = tuple[int, int]

#: Scheme prefix marking an artifact-read ref as a bead read.
BEAD_READ_REF_PREFIX = "bead:"


@dataclass(frozen=True)
class _BeadTouchDisplayEvent:
    """One indexed touch paired with an optional family role label.

    ``agent_label`` is ``None`` for ordinary (single-member) rows so the
    existing per-agent shape is preserved; family rows set it to the
    producing member's compact role label (e.g. ``plan``, ``coder``).
    """

    touch: BeadTouch
    agent_label: str | None = None


@dataclass(frozen=True)
class BeadTouchEntry:
    """One bead's merged view for the panel's ``Beads:`` sub-section.

    ``verbs`` folds every contributing source: the indexed durable verbs
    plus ``read`` for audited ``bead:`` artifact reads. ``own`` marks a
    bead the agent was assigned even when it never touched it (no verbs).
    ``agent_label`` is the one family-producer label shared by the
    entry's labeled contributors; mixed-producer beads report ``None``.
    """

    bead_id: str
    title: str = ""
    verbs: dict[str, int] = field(default_factory=dict)
    first_at: str = ""
    last_at: str = ""
    own: bool = False
    agent_label: str | None = None


@dataclass
class _BeadTouchesCacheEntry:
    events: tuple[_BeadTouchDisplayEvent, ...]
    index_mtime_ns: int
    index_size: int
    views_mtime_ns: int = 0
    views_size: int = 0
    last_read_monotonic: float = 0.0


@dataclass
class _BeadTouchesContextCacheEntry:
    events: tuple[_BeadTouchDisplayEvent, ...]
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


def _parse_moment(value: str | None) -> datetime | None:
    """Parse an RFC 3339 timestamp, or return ``None`` when unusable."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _touch_sort_key(touch: BeadTouch) -> tuple[float, str]:
    moment = _parse_moment(touch.last_at)
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
    to one agent while the family loader attributes them per member, both
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
) -> tuple[_BeadTouchDisplayEvent, ...]:
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
) -> tuple[_BeadTouchDisplayEvent, ...]:
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
        _BeadTouchDisplayEvent(touch=touch) for touch in ordered[:MAX_KEPT_TOUCHES]
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
) -> tuple[_BeadTouchDisplayEvent, ...]:
    """Return display bead-touches for an agent-family context, newest first.

    For an ordinary row with no follow-up family members this delegates to
    the per-agent loader and wraps each touch with no label, preserving the
    single-agent shape. For a family row it reads the index once, attributes
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
) -> tuple[_BeadTouchDisplayEvent, ...]:
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
    matched: list[_BeadTouchDisplayEvent] = []
    for touch in all_touches:
        for label, globalized_name, local_name in matchers:
            if touch_matches_agent(
                touch.actor,
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            ):
                matched.append(_BeadTouchDisplayEvent(touch=touch, agent_label=label))
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
                matched.append(_BeadTouchDisplayEvent(touch=touch, agent_label=label))
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


def _canonical_bead_id(value: str | None) -> str:
    """Return the comparison key for a bead id or ``bead:`` read ref.

    Trims whitespace and strips one ``bead:`` scheme prefix, so a
    ``bead:sase-14j.4`` read ref and the bare ``sase-14j.4`` touch id never
    split into two rows. Matching stays exact after that: no case folding
    and no suffix matching, because bead ids and agent names both use
    dotted suffixes and a loose match would cross-attribute.
    """
    text = (value or "").strip()
    if text.startswith(BEAD_READ_REF_PREFIX):
        text = text.removeprefix(BEAD_READ_REF_PREFIX).strip()
    return text


def own_bead_ids_for_agent(agent: Agent) -> tuple[str, ...]:
    """Return the bead ids the agent was assigned, in precedence order.

    Mirrors the ``_agent_bead_id`` fallback chain (explicit phase bead,
    explicit epic bead, bead id derived from a ``sase bead work`` agent
    name) but collects every distinct id instead of the first, because an
    agent assigned but never touching either bead still owns both rows.
    """
    ordered: list[str] = []
    candidates = [agent.phase_bead_id, agent.epic_bead_id, _derived_bead_id(agent)]
    for candidate in candidates:
        text = (candidate or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    return tuple(ordered)


def _derived_bead_id(agent: Agent) -> str | None:
    try:
        from sase.agent.bead_display import derive_agent_bead_id_from_name

        return derive_agent_bead_id_from_name(
            agent.presented_agent_name or agent.agent_name
        )
    except Exception:
        return None


class _BeadBucket:
    """Mutable per-bead accumulator behind :func:`merge_bead_touch_entries`."""

    def __init__(self, bead_id: str) -> None:
        self.bead_id = bead_id
        self.title = ""
        self.verbs: dict[str, int] = {}
        self._moments: list[tuple[datetime, str]] = []
        self.own = False
        self._labels: set[str] = set()

    def add_verbs(self, verbs: dict[str, int]) -> None:
        for verb, count in verbs.items():
            if count > 0:
                self.verbs[verb] = self.verbs.get(verb, 0) + count

    def add_moment(self, value: str | None) -> None:
        moment = _parse_moment(value)
        if moment is not None:
            self._moments.append((moment, (value or "").strip()))

    def add_title(self, title: str | None) -> None:
        cleaned = (title or "").strip()
        if not self.title and cleaned:
            self.title = cleaned

    def add_label(self, label: str | None) -> None:
        if label is not None:
            self._labels.add(label)

    def entry(self) -> BeadTouchEntry:
        first_at = ""
        last_at = ""
        if self._moments:
            ordered = sorted(self._moments, key=lambda item: item[0])
            first_at = ordered[0][1]
            last_at = ordered[-1][1]
        label = next(iter(self._labels)) if len(self._labels) == 1 else None
        return BeadTouchEntry(
            bead_id=self.bead_id,
            title=self.title,
            verbs=dict(self.verbs),
            first_at=first_at,
            last_at=last_at,
            own=self.own,
            agent_label=label,
        )


def _entry_rank(entry: BeadTouchEntry) -> tuple[float, str]:
    moment = _parse_moment(entry.last_at)
    epoch = moment.timestamp() if moment is not None else float("-inf")
    return (-epoch, entry.bead_id)


def merge_bead_touch_entries(
    touches: tuple[_BeadTouchDisplayEvent, ...] | list[_BeadTouchDisplayEvent],
    reads: tuple[ArtifactReadDisplayEvent, ...] | list[ArtifactReadDisplayEvent],
    own_bead_ids: tuple[str, ...] | list[str] = (),
) -> tuple[BeadTouchEntry, ...]:
    """Fold touches, audited bead reads, and own beads into one ranked view.

    Pure function over its three inputs so it is testable without a store:
    touch rows (durable index rows plus synthesized ``viewed`` rows from the
    machine-local view log, already ordered durable-first so durable titles
    win), the already-loaded audited artifact reads (only ``bead:`` refs
    contribute; anything else is ignored so a bead read can never
    double-list), and the agent's own bead ids. Emits one entry per
    bead with merged verb counts, the newest timestamp across all sources,
    the title from whichever source has one, and the ``own`` mark. Bead ids
    are compared after :func:`_canonical_bead_id` so a ``bead:``-prefixed ref
    and a bare id never split into two rows. Ranking is newest-touch-first
    with a bead-id tiebreak; timestamp-less own-only beads sort last.
    """
    buckets: dict[str, _BeadBucket] = {}
    own_keys = {
        key for key in (_canonical_bead_id(value) for value in own_bead_ids) if key
    }

    def bucket_for(key: str, display_id: str) -> _BeadBucket:
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = _BeadBucket(display_id)
        return bucket

    for display in touches:
        key = _canonical_bead_id(display.touch.bead_id)
        if not key:
            continue
        bucket = bucket_for(key, display.touch.bead_id.strip())
        bucket.add_title(display.touch.title)
        bucket.add_verbs(display.touch.verbs)
        bucket.add_moment(display.touch.first_at)
        bucket.add_moment(display.touch.last_at)
        bucket.add_label(display.agent_label)

    for read_display in reads:
        ref = (read_display.event.ref or "").strip()
        if not ref.startswith(BEAD_READ_REF_PREFIX):
            continue
        key = _canonical_bead_id(ref)
        if not key:
            continue
        bucket = bucket_for(key, key)
        bucket.add_verbs({"read": 1})
        bucket.add_moment(read_display.event.timestamp)
        bucket.add_label(read_display.agent_label)

    for key in own_keys:
        bucket = bucket_for(key, key)
        bucket.own = True

    return tuple(
        sorted((bucket.entry() for bucket in buckets.values()), key=_entry_rank)
    )


__all__: list[str] = [
    "BEAD_READ_REF_PREFIX",
    "MAX_KEPT_TOUCHES",
    "BeadTouchEntry",
    "load_bead_touches_for_agent_context",
    "merge_bead_touch_entries",
    "own_bead_ids_for_agent",
]

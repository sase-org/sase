"""Per-agent bead-touch loader with identity-keyed result caches.

Reads only the rows one agent context claims: the touch index and the
legacy ``bead_views.jsonl`` log are queried in Rust for the context's
ordered member selectors, and only matching rows are constructed in
Python. No whole-project touch or view snapshot is retained; the only
long-lived owners are the two bounded per-agent/context result caches
(128 entries each, 50 rows per entry).

Refresh runs at the three off-hot-path sites owned by the host-refresh
phase (post-mutation, post-sync, lumberjack tick), so a stale index
returns stale answers here rather than paying for freshness on the
panel's clock. A missing, truncated, or unparseable source is a cache
miss that returns no rows, never an error. A failed query is never
cached under an unchanged token: the next poll retries.

The legacy, no-longer-written ``bead_views.jsonl`` log is folded behind
the durable index rows as ``viewed``-only synthetic touches.

Bead mutations record ``$SASE_AGENT_NAME`` as the event actor, which holds
the session container name for pre-rename roots and in-process continuation
turns. The loader therefore accepts the container name as an actor alias
wherever the whole session is in view (a session row, or a session root
with no visible followups). Member matchers keep precedence, alias touches
stay unlabeled, and non-root turn rows never take the alias.
"""

from __future__ import annotations

import fcntl
import time
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui._bead_touches_shared import (
    BeadTouchDisplayEvent,
    parse_moment,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.bead.bead_views import bead_views_log_path
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    globalize_owned_agent_name,
)
from sase.core.bead_touch_index_facade import (
    BeadTouch,
    TouchMemberRow,
    TouchQueryMember,
    TouchSourceIdentity,
    merge_view_touches,
    query_bead_view_members,
    query_touch_index_members,
)
from sase.core.bead_touch_index_store import touch_index_path
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file

MAX_KEPT_TOUCHES = 50
_MIN_REREAD_INTERVAL_S = 0.5
_MAX_DERIVED_CACHE_ENTRIES = 128
#: ``(dev, ino, mtime_ns, size, missing)``: an atomic replacement with
#: equal size and mtime still changes ``(dev, ino)`` and revalidates.
_SourceIdentity = tuple[int, int, int, int, bool]


@dataclass
class _BeadTouchesCacheEntry:
    events: tuple[BeadTouchDisplayEvent, ...]
    index: _SourceIdentity
    views: _SourceIdentity
    last_read_monotonic: float = 0.0


@dataclass
class _BeadTouchesContextCacheEntry:
    events: tuple[BeadTouchDisplayEvent, ...]
    index: _SourceIdentity
    views: _SourceIdentity
    last_read_monotonic: float = 0.0


_bead_touches_cache: BoundedLRUCache[tuple[str, str], _BeadTouchesCacheEntry] = (
    BoundedLRUCache(_MAX_DERIVED_CACHE_ENTRIES)
)
_bead_touches_context_cache: BoundedLRUCache[
    tuple[str, tuple[str, ...]], _BeadTouchesContextCacheEntry
] = BoundedLRUCache(_MAX_DERIVED_CACHE_ENTRIES)


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


def _source_identity_for_path(path: Path) -> _SourceIdentity:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (0, 0, 0, 0, True)
    except OSError:
        return (0, 0, 0, 0, True)
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        False,
    )


def _identity_from_wire(source: TouchSourceIdentity) -> _SourceIdentity:
    return (
        int(source.dev),
        int(source.ino),
        int(source.mtime_ns),
        int(source.size),
        bool(source.missing),
    )


def _cache_entry_identities(
    entry: _BeadTouchesCacheEntry | _BeadTouchesContextCacheEntry,
) -> tuple[_SourceIdentity, _SourceIdentity]:
    return (entry.index, entry.views)


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


def _session_container_alias(agent: Agent) -> str | None:
    """Return the session-container actor alias for a session root row.

    Bead mutations record ``$SASE_AGENT_NAME`` as the event actor, and for a
    pre-rename root or an in-process continuation turn that variable holds
    the session container name (``agent_meta.json``'s ``agent_session``),
    not a concrete ``--plan``/``--code`` turn name. The container name is
    therefore a legitimate identity spelling for the whole session, and the
    loader accepts it as an actor alias wherever the whole session is in
    view. Members keep precedence (callers test them first), alias touches
    are unlabeled, and non-root turn rows never take the alias. Returns
    ``None`` when there is no usable alias: non-root rows, a blank session
    name, or a never-renamed root whose container name already equals its
    own ``agent_name`` (exact matching covers that case). Never raises.
    """
    try:
        if not agent.is_agent_session_root_entry:
            return None
        alias = agent.agent_session_reference_name()
    except Exception:
        return None
    if not isinstance(alias, str) or not alias.strip():
        return None
    text = alias.strip()
    try:
        own = agent.agent_name or agent.presented_agent_name
    except Exception:
        own = None
    if isinstance(own, str) and text == own.strip():
        return None
    return text


def _ordered_members(
    agent: Agent, identity: AgentIdentitySnapshot
) -> tuple[list[tuple[str | None, TouchQueryMember]], list[TouchQueryMember]]:
    """Return ``([(label, member), ...], [member, ...])`` for one agent.

    Members keep file order with the trailing session-container alias last
    so it never shadows a member; the alias is unlabeled. For an ordinary
    row the member list holds exactly the agent itself.
    """
    from sase.ace.tui.agent_context_members import build_context_members

    members = build_context_members(agent)
    labelled: list[tuple[str | None, TouchQueryMember]] = []
    if len(members) <= 1:
        globalized_name, local_name = _globalized_name_for_agent(agent, identity)
        labelled.append((None, TouchQueryMember(globalized_name, local_name)))
    else:
        for member in members:
            globalized_name, local_name = _member_match_params(
                member.agent_name, identity
            )
            labelled.append(
                (member.label, TouchQueryMember(globalized_name, local_name))
            )
    alias = _session_container_alias(agent)
    if alias is not None:
        globalized_name, local_name = _member_match_params(alias, identity)
        labelled.append((None, TouchQueryMember(globalized_name, local_name)))
    return labelled, [member for _, member in labelled]


def _query_index_members(
    index_path: Path,
    touch_members: list[TouchQueryMember],
    identity: AgentIdentitySnapshot,
) -> tuple[list[TouchMemberRow], _SourceIdentity, str] | None:
    """Return claimed index rows, or ``None`` when the query failed.

    A failed query is never cached: the next poll retries instead of
    sticking an error-shaped empty answer to an unchanged token.
    """
    try:
        rows, source, generation, _schema_version = query_touch_index_members(
            index_path, touch_members, identity
        )
    except Exception:
        return None
    return rows, _identity_from_wire(source), generation


def _query_view_members(
    views_path: Path,
    touch_members: list[TouchQueryMember],
    identity: AgentIdentitySnapshot,
) -> tuple[list[TouchMemberRow], _SourceIdentity] | None:
    """Return claimed folded view rows, or ``None`` when the scan failed.

    The views log is append-only and small; an incomplete scan or read
    failure degrades to no views rather than an error, so a missing log
    simply contributes no ``viewed`` rows.
    """
    try:
        with locked_file(views_path.with_suffix(".lock"), fcntl.LOCK_SH):
            rows, source, complete = query_bead_view_members(
                views_path, touch_members, identity
            )
    except Exception:
        return None
    if not complete:
        return None
    return rows, _identity_from_wire(source)


def _resolve_source_paths(
    project: str,
) -> tuple[Path, Path | None] | None:
    """Return ``(index_path, views_path)`` for one project, if resolvable."""
    try:
        index_path = touch_index_path(project)
    except Exception:
        return None
    try:
        views_path: Path | None = bead_views_log_path(project)
    except Exception:
        views_path = None
    return index_path, views_path


def _load_claimed_rows(
    index_path: Path,
    views_path: Path | None,
    touch_members: list[TouchQueryMember],
    identity: AgentIdentitySnapshot,
) -> (
    tuple[list[TouchMemberRow], list[TouchMemberRow], _SourceIdentity, _SourceIdentity]
    | None
):
    """Query the index and views for one agent's ordered members.

    Returns ``(index_rows, view_rows, index_identity, views_identity)``
    with member ordinals attached for context attribution. ``None`` only
    when the index query itself failed; a failed or incomplete views scan
    degrades to no views under the views file's current identity so the
    next mutation still revalidates.
    """
    claimed = _query_index_members(index_path, touch_members, identity)
    if claimed is None:
        return None
    index_rows, index_identity, _generation = claimed
    if views_path is None:
        return index_rows, [], index_identity, (0, 0, 0, 0, True)
    views_claimed = _query_view_members(views_path, touch_members, identity)
    if views_claimed is None:
        return index_rows, [], index_identity, _source_identity_for_path(views_path)
    view_rows, views_identity = views_claimed
    return index_rows, view_rows, index_identity, views_identity


def _load_bead_touches_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_TOUCHES
) -> tuple[BeadTouchDisplayEvent, ...]:
    """Return indexed touches attributed to ``agent``, newest first.

    A session root entry with no visible followups also matches its
    session-container alias (see :func:`_session_container_alias`), so a
    root renamed to ``--plan`` still credits touches recorded under the
    container name. Uses an identity-keyed cache + throttle to make repeated
    calls cheap on the j/k navigation hot path. Never raises: any failure
    is an empty answer.
    """
    try:
        return _load_bead_touches_for_agent_inner(agent, limit=limit)
    except Exception:
        return ()


def _load_bead_touches_for_agent_inner(
    agent: Agent, *, limit: int
) -> tuple[BeadTouchDisplayEvent, ...]:
    from sase.ace.tui.agent_context_members import build_context_members

    project = _project_name_for_agent(agent)
    if project is None:
        return ()
    if len(build_context_members(agent)) > 1:
        # A session row delegates to the context loader below; this path
        # only serves ordinary single-member rows (plus, for a session
        # root with no visible followups, the trailing container alias).
        return load_bead_touches_for_agent_context(agent, limit=limit)
    identity = AgentIdentitySnapshot.current()
    resolved = _resolve_source_paths(project)
    if resolved is None:
        return ()
    index_path, views_path = resolved
    _labelled, touch_members = _ordered_members(agent, identity)

    now = time.monotonic()
    key = _cache_key(project, agent)
    cached = _bead_touches_cache.peek(key)
    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent:
            _bead_touches_cache.touch(key)
            return cached.events[:limit]
        current_identities = (
            _source_identity_for_path(index_path),
            _source_identity_for_path(views_path)
            if views_path is not None
            else (0, 0, 0, 0, True),
        )
        if current_identities == _cache_entry_identities(cached):
            _bead_touches_cache.touch(key)
            return cached.events[:limit]

    current = _load_claimed_rows(index_path, views_path, touch_members, identity)
    if current is None:
        return ()
    index_rows, view_rows, index_identity, views_identity = current

    ordered = sorted(
        merge_view_touches(
            [row.touch for row in index_rows],
            [row.touch for row in view_rows],
        ),
        key=_touch_sort_key,
        reverse=True,
    )
    capped = tuple(
        BeadTouchDisplayEvent(touch=touch) for touch in ordered[:MAX_KEPT_TOUCHES]
    )
    _bead_touches_cache[key] = _BeadTouchesCacheEntry(
        events=capped,
        index=index_identity,
        views=views_identity,
        last_read_monotonic=now,
    )
    return capped[:limit]


def load_bead_touches_for_agent_context(
    agent: Agent, *, limit: int = MAX_KEPT_TOUCHES
) -> tuple[BeadTouchDisplayEvent, ...]:
    """Return display bead-touches for an agent-session context, newest first.

    For an ordinary row with no follow-up session members this delegates to
    the per-agent loader and wraps each touch with no label, preserving the
    single-agent shape. For a session row it queries the index once,
    attributes each claimed row to the first member whose identity matches
    its actor, sorts newest first, caps to ``MAX_KEPT_TOUCHES``, and labels
    each kept touch with its producer's compact role. Touches recorded under
    the session container name match a trailing alias matcher (see
    :func:`_session_container_alias`) and stay unlabeled, because one
    ``(actor, bead)`` row can merge several turns' events. Never raises.
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

    project = _project_name_for_agent(agent)
    if project is None:
        return ()
    identity = AgentIdentitySnapshot.current()
    resolved = _resolve_source_paths(project)
    if resolved is None:
        return ()
    index_path, views_path = resolved
    labelled, touch_members = _ordered_members(agent, identity)

    now = time.monotonic()
    key = (project, context_cache_key(members))
    cached = _bead_touches_context_cache.peek(key)
    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent:
            _bead_touches_context_cache.touch(key)
            return cached.events[:limit]
        current_identities = (
            _source_identity_for_path(index_path),
            _source_identity_for_path(views_path)
            if views_path is not None
            else (0, 0, 0, 0, True),
        )
        if current_identities == _cache_entry_identities(cached):
            _bead_touches_context_cache.touch(key)
            return cached.events[:limit]

    current = _load_claimed_rows(index_path, views_path, touch_members, identity)
    if current is None:
        return ()
    index_rows, view_rows, index_identity, views_identity = current

    labels = [label for label, _ in labelled]
    matched: list[BeadTouchDisplayEvent] = [
        BeadTouchDisplayEvent(touch=row.touch, agent_label=labels[row.member_index])
        for row in index_rows
    ]
    matched.extend(
        BeadTouchDisplayEvent(touch=row.touch, agent_label=labels[row.member_index])
        for row in view_rows
    )

    matched.sort(key=lambda item: _touch_sort_key(item.touch), reverse=True)
    capped = tuple(matched[:MAX_KEPT_TOUCHES])
    _bead_touches_context_cache[key] = _BeadTouchesContextCacheEntry(
        events=capped,
        index=index_identity,
        views=views_identity,
        last_read_monotonic=now,
    )
    return capped[:limit]

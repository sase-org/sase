"""Loader for per-agent ``sase memory read`` audit events."""

from __future__ import annotations

import fcntl
import time
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.main.init_memory.config import project_memory_name
from sase.memory._read_log_query_facade import (
    MemoryAuditSourceIdentity,
    query_memory_audit,
)
from sase.memory.locks import locked_file
from sase.memory.read_log import (
    MemoryReadEvent,
    memory_read_log_path,
)

MAX_KEPT_READS = 50
_MIN_REREAD_INTERVAL_S = 0.5
_MAX_DERIVED_CACHE_ENTRIES = 128
_SourceIdentity = tuple[int, int, int, int, bool]


@dataclass(frozen=True)
class MemoryReadDisplayEvent:
    """A memory-read event paired with an optional session role label.

    ``agent_label`` is ``None`` for ordinary (single-member) rows so the
    existing per-agent visual shape is preserved; session rows set it to the
    producing member's compact role label (e.g. ``plan``, ``coder``).
    """

    event: MemoryReadEvent
    agent_label: str | None = None


@dataclass
class _MemoryReadsCacheEntry:
    events: tuple[MemoryReadEvent, ...]
    identity: _SourceIdentity
    last_read_monotonic: float


@dataclass
class _MemoryReadsContextCacheEntry:
    events: tuple[MemoryReadDisplayEvent, ...]
    identity: _SourceIdentity
    last_read_monotonic: float


_memory_reads_cache: BoundedLRUCache[tuple[str, str], _MemoryReadsCacheEntry] = (
    BoundedLRUCache(_MAX_DERIVED_CACHE_ENTRIES)
)
_memory_reads_context_cache: BoundedLRUCache[
    tuple[str, tuple[str, ...]], _MemoryReadsContextCacheEntry
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


def _log_source_identity(path: Path) -> _SourceIdentity:
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


def _audit_source_to_identity(
    source: MemoryAuditSourceIdentity,
) -> _SourceIdentity:
    return (
        int(source.dev),
        int(source.ino),
        int(source.mtime_ns),
        int(source.size),
        bool(source.missing),
    )


def _query_single_agent_rows(
    log_path: Path,
    *,
    artifacts_dir: str | None,
    agent_name: str | None,
) -> tuple[tuple[MemoryReadEvent, ...], _SourceIdentity] | None:
    try:
        with locked_file(log_path.with_suffix(".lock"), fcntl.LOCK_SH):
            rows, source = query_memory_audit(
                log_path,
                members=[
                    {
                        "artifacts_dir": artifacts_dir,
                        "agent_name": agent_name,
                    }
                ],
                limit=MAX_KEPT_READS,
                deduplicate=False,
            )
    except Exception:
        return None
    events = tuple(row.event for row in rows)
    return events, _audit_source_to_identity(source)


def _load_memory_reads_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_READS
) -> tuple[MemoryReadEvent, ...]:
    """Return memory-read events attributed to ``agent``, newest first.

    Uses a bounded targeted Rust query plus an identity-keyed cache and
    throttle to make repeated calls cheap on the j/k navigation hot path.
    """
    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = memory_read_log_path(project)
    now = time.monotonic()
    key = _cache_key(project, agent)
    cached = _memory_reads_cache.peek(key)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent:
            _memory_reads_cache.touch(key)
            return cached.events[:limit]
        if _log_source_identity(log_path) == cached.identity:
            _memory_reads_cache.touch(key)
            return cached.events[:limit]

    queried = _query_single_agent_rows(
        log_path,
        artifacts_dir=agent.get_artifacts_dir(),
        agent_name=agent.agent_name,
    )
    if queried is None:
        if cached is not None:
            return cached.events[:limit]
        return ()
    events, identity = queried
    # Rust already returns newest-first capped rows.
    capped = events[:MAX_KEPT_READS]
    _memory_reads_cache[key] = _MemoryReadsCacheEntry(
        events=capped,
        identity=identity,
        last_read_monotonic=time.monotonic(),
    )
    return capped[:limit]


def load_memory_reads_for_agent_context(
    agent: Agent, *, limit: int = MAX_KEPT_READS
) -> tuple[MemoryReadDisplayEvent, ...]:
    """Return display memory-reads for an agent-session context, newest first.

    For an ordinary row with no follow-up session members this delegates to
    :func:`_load_memory_reads_for_agent` and wraps each event with no label,
    preserving the single-agent visual shape. For a session row it issues one
    targeted Rust query for the ordered members, de-duplicates by event id,
    sorts newest first, caps to ``MAX_KEPT_READS``, and labels each kept event
    with its producer's compact role.
    """
    from sase.ace.tui.agent_context_members import (
        build_context_members,
        context_cache_key,
    )

    members = build_context_members(agent)
    if len(members) <= 1:
        events = _load_memory_reads_for_agent(agent, limit=limit)
        return tuple(MemoryReadDisplayEvent(event=event) for event in events)

    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = memory_read_log_path(project)
    now = time.monotonic()
    key = (project, context_cache_key(members))
    cached = _memory_reads_context_cache.peek(key)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent:
            _memory_reads_context_cache.touch(key)
            return cached.events[:limit]
        if _log_source_identity(log_path) == cached.identity:
            _memory_reads_context_cache.touch(key)
            return cached.events[:limit]

    payload = [
        {
            "artifacts_dir": member.artifacts_dir,
            "agent_name": member.agent_name,
        }
        for member in members
    ]
    try:
        with locked_file(log_path.with_suffix(".lock"), fcntl.LOCK_SH):
            rows, source = query_memory_audit(
                log_path,
                members=payload,
                limit=MAX_KEPT_READS,
                deduplicate=True,
            )
    except Exception:
        if cached is not None:
            return cached.events[:limit]
        return ()
    identity = _audit_source_to_identity(source)
    display = tuple(
        MemoryReadDisplayEvent(
            event=row.event,
            agent_label=members[row.member_index].label
            if 0 <= row.member_index < len(members)
            else None,
        )
        for row in rows
    )
    capped = display[:MAX_KEPT_READS]
    _memory_reads_context_cache[key] = _MemoryReadsContextCacheEntry(
        events=capped,
        identity=identity,
        last_read_monotonic=time.monotonic(),
    )
    return capped[:limit]

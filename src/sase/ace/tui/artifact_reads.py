"""Loader for per-agent ``sase artifact read`` audit events."""

from __future__ import annotations

import fcntl
import time
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.memory.locks import locked_file
from sase.artifact_read_log import (
    ArtifactReadAuditRow,
    ArtifactReadAuditSourceIdentity,
    ArtifactReadEvent,
    artifact_read_log_path,
    query_artifact_read_events,
)
from sase.main.init_memory.config import project_memory_name

MAX_KEPT_READS = 50
_MIN_REREAD_INTERVAL_S = 0.5
_MAX_DERIVED_CACHE_ENTRIES = 128
_SourceIdentity = tuple[int, int, int, int, bool]


@dataclass(frozen=True)
class ArtifactReadDisplayEvent:
    """An artifact-read event paired with an optional session role label.

    ``agent_label`` is ``None`` for ordinary (single-member) rows so the
    existing per-agent visual shape is preserved; session rows set it to the
    producing member's compact role label (e.g. ``plan``, ``coder``).
    """

    event: ArtifactReadEvent
    agent_label: str | None = None


@dataclass(frozen=True)
class ArtifactReadRefSpec:
    """Durable artifact-read identity carried with a hinted resolved path."""

    ref: str
    cwd: str | None


@dataclass
class _ArtifactReadsCacheEntry:
    events: tuple[ArtifactReadEvent, ...]
    identity: _SourceIdentity
    last_read_monotonic: float


@dataclass
class _ArtifactReadsContextCacheEntry:
    events: tuple[ArtifactReadDisplayEvent, ...]
    identity: _SourceIdentity
    last_read_monotonic: float


_artifact_reads_cache: BoundedLRUCache[tuple[str, str], _ArtifactReadsCacheEntry] = (
    BoundedLRUCache(_MAX_DERIVED_CACHE_ENTRIES)
)
_artifact_reads_context_cache: BoundedLRUCache[
    tuple[str, tuple[str, ...]], _ArtifactReadsContextCacheEntry
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


def _log_source_identity(path: Path) -> _SourceIdentity | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (0, 0, 0, 0, True)
    except OSError:
        return None
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        False,
    )


def _audit_source_to_identity(
    source: ArtifactReadAuditSourceIdentity,
) -> _SourceIdentity:
    return (
        int(source.dev),
        int(source.ino),
        int(source.mtime_ns),
        int(source.size),
        bool(source.missing),
    )


def _query_artifact_read_rows(
    log_path: Path,
    *,
    members: list[dict[str, str | None]],
    deduplicate: bool,
) -> tuple[list[ArtifactReadAuditRow], _SourceIdentity] | None:
    try:
        with locked_file(log_path.with_suffix(".lock"), fcntl.LOCK_SH):
            rows, source = query_artifact_read_events(
                log_path,
                members=members,
                limit=MAX_KEPT_READS,
                deduplicate=deduplicate,
            )
    except Exception:
        return None
    return rows, _audit_source_to_identity(source)


def _load_artifact_reads_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_READS
) -> tuple[ArtifactReadEvent, ...]:
    """Return artifact-read events attributed to ``agent``, newest first.

    Uses a source-identity-keyed cache and throttle to make repeated calls
    cheap on the j/k navigation hot path.
    """
    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = artifact_read_log_path(project)
    now = time.monotonic()
    key = _cache_key(project, agent)
    cached = _artifact_reads_cache.peek(key)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        current_identity = _log_source_identity(log_path)
        if recent or (
            current_identity is not None and current_identity == cached.identity
        ):
            _artifact_reads_cache.touch(key)
            return cached.events[:limit]

    queried = _query_artifact_read_rows(
        log_path,
        members=[
            {
                "artifacts_dir": agent.get_artifacts_dir(),
                "agent_name": agent.agent_name,
            }
        ],
        deduplicate=False,
    )
    if queried is None:
        if cached is not None:
            return cached.events[:limit]
        return ()
    rows, identity = queried
    capped = tuple(row.event for row in rows[:MAX_KEPT_READS])
    _artifact_reads_cache[key] = _ArtifactReadsCacheEntry(
        events=capped,
        identity=identity,
        last_read_monotonic=now,
    )
    return capped[:limit]


def load_artifact_reads_for_agent_context(
    agent: Agent, *, limit: int = MAX_KEPT_READS
) -> tuple[ArtifactReadDisplayEvent, ...]:
    """Return display artifact-reads for an agent-session context, newest first.

    For an ordinary row with no follow-up session members this delegates to
    :func:`_load_artifact_reads_for_agent` and wraps each event with no label,
    preserving the single-agent visual shape. For a session row it queries
    only matching members, de-duplicates by event id, sorts newest first, caps
    to ``MAX_KEPT_READS``, and labels each kept event with its producer's
    compact role.
    """
    from sase.ace.tui.agent_context_members import (
        build_context_members,
        context_cache_key,
    )

    members = build_context_members(agent)
    if len(members) <= 1:
        events = _load_artifact_reads_for_agent(agent, limit=limit)
        return tuple(ArtifactReadDisplayEvent(event=event) for event in events)

    project = _project_name_for_agent(agent)
    if project is None:
        return ()

    log_path = artifact_read_log_path(project)
    now = time.monotonic()
    key = (project, context_cache_key(members))
    cached = _artifact_reads_context_cache.peek(key)
    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        current_identity = _log_source_identity(log_path)
        if recent or (
            current_identity is not None and current_identity == cached.identity
        ):
            _artifact_reads_context_cache.touch(key)
            return cached.events[:limit]

    payload_members = [
        {
            "artifacts_dir": member.artifacts_dir,
            "agent_name": member.agent_name,
        }
        for member in members
    ]
    queried = _query_artifact_read_rows(
        log_path,
        members=payload_members,
        deduplicate=True,
    )
    if queried is None:
        if cached is not None:
            return cached.events[:limit]
        return ()
    rows, identity = queried
    capped = tuple(
        ArtifactReadDisplayEvent(
            event=row.event,
            agent_label=members[row.member_index].label
            if 0 <= row.member_index < len(members)
            else None,
        )
        for row in rows[:MAX_KEPT_READS]
    )
    _artifact_reads_context_cache[key] = _ArtifactReadsContextCacheEntry(
        events=capped,
        identity=identity,
        last_read_monotonic=now,
    )
    return capped[:limit]

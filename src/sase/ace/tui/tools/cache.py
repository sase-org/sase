"""Shared cached fetch path for agent tool-call artifacts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.time import local_now, to_local

from ._entry import ToolCallEntry
from .reader import (
    TOOL_CALLS_FILENAME,
    discover_related_tool_artifact_dirs_cached,
    read_tool_calls_for_agent,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


_MIN_REREAD_INTERVAL_S = 0.5


@dataclass
class _ToolsCacheEntry:
    """Cache entry for agent tool-call records."""

    entries: tuple[ToolCallEntry, ...] | None
    fetch_time: datetime
    artifact_mtime_ns: int = 0
    discovered_dirs: list[Path] = field(default_factory=list)
    parent_mtime_ns: int = 0
    last_worker_monotonic: float = 0.0


_tools_cache: dict[str, _ToolsCacheEntry] = {}
ToolsCacheEntry = _ToolsCacheEntry
tools_cache = _tools_cache


def get_cache_key(agent: Agent) -> str:
    """Generate a unique cache key for an agent's tool-call output."""
    parts = [agent.cl_name, agent.agent_type.value]
    if agent.workspace_num is not None:
        parts.append(str(agent.workspace_num))
    if agent.raw_suffix:
        parts.append(agent.raw_suffix)
    return ":".join(parts)


def _max_mtime_ns_for_paths(paths: list[Path]) -> int:
    latest = 0
    for path in paths:
        try:
            stat_result = path.stat()
        except OSError:
            continue
        if stat_result.st_mtime_ns > latest:
            latest = stat_result.st_mtime_ns
    return latest


def _resolve_artifacts_dir(agent: Agent) -> str | Path | None:
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None
    artifacts_dir = get_artifacts_dir()
    if not isinstance(artifacts_dir, (str, Path)) or not artifacts_dir:
        return None
    return artifacts_dir


def _normalize_entries(
    entries: list[ToolCallEntry] | tuple[ToolCallEntry, ...] | None,
) -> tuple[ToolCallEntry, ...] | None:
    if entries is None:
        return None
    return tuple(entries)


def peek_cached_tool_calls(agent: Agent) -> tuple[ToolCallEntry, ...] | None:
    """Return cached entries for ``agent`` without touching the filesystem."""
    entry = _tools_cache.get(get_cache_key(agent))
    return None if entry is None else entry.entries


def peek_tool_calls_cache_entry(agent: Agent) -> _ToolsCacheEntry | None:
    """Return the raw cache entry for no-I/O callers that need metadata."""
    return _tools_cache.get(get_cache_key(agent))


def cached_tool_calls_end_reference(agent: Agent) -> datetime | None:
    """Return the artifact mtime watermark as a stable end reference."""
    entry = peek_tool_calls_cache_entry(agent)
    if entry is None or entry.artifact_mtime_ns <= 0:
        return None
    timestamp = datetime.fromtimestamp(
        entry.artifact_mtime_ns / 1_000_000_000,
        tz=UTC,
    )
    return to_local(timestamp)


def cached_tool_calls_have_pending(agent: Agent) -> bool:
    """Return whether cached entries include any pending tool call."""
    entries = peek_cached_tool_calls(agent)
    if entries is None:
        return False
    return any(entry.status == "pending" for entry in entries)


def slow_tool_sources_have_pending(agent: Agent) -> bool:
    """Return whether any cached source entries include a pending tool call.

    This is intentionally peek-only for event-loop callers. It checks the
    selected row's cache key plus agent-entry runtime children, matching the
    source builder's fetch scope without resolving artifact directories.
    """
    if cached_tool_calls_have_pending(agent):
        return True
    return any(
        child.is_agent_entry and cached_tool_calls_have_pending(child)
        for child in getattr(agent, "runtime_children", ())
    )


def should_throttle_tool_call_fetch(agent: Agent) -> bool:
    """Return whether a worker fetch was started too recently."""
    entry = peek_tool_calls_cache_entry(agent)
    return (
        entry is not None
        and (time.monotonic() - entry.last_worker_monotonic) < _MIN_REREAD_INTERVAL_S
    )


def mark_tool_call_fetch_started(agent: Agent) -> None:
    """Record worker scheduling time on a warm cache entry."""
    entry = peek_tool_calls_cache_entry(agent)
    if entry is not None:
        entry.last_worker_monotonic = time.monotonic()


def invalidate_cached_tool_calls(agent: Agent) -> None:
    """Force the next worker fetch to re-read artifacts."""
    entry = peek_tool_calls_cache_entry(agent)
    if entry is not None:
        entry.artifact_mtime_ns = -1
        entry.last_worker_monotonic = time.monotonic()


def fetch_tool_calls_cached(agent: Agent) -> tuple[ToolCallEntry, ...] | None:
    """Fetch tool calls using the shared mtime-keyed cache.

    This function may stat/read artifact files and is intended for worker
    threads, not the Textual event loop.
    """
    now_mono = time.monotonic()
    cache_key = get_cache_key(agent)
    prior = _tools_cache.get(cache_key)
    artifacts_dir = _resolve_artifacts_dir(agent)

    if artifacts_dir is None:
        entries = _normalize_entries(read_tool_calls_for_agent(agent))
        _tools_cache[cache_key] = _ToolsCacheEntry(
            entries=entries,
            fetch_time=local_now(),
            last_worker_monotonic=now_mono,
        )
        return entries

    cached_dirs = prior.discovered_dirs if prior is not None else None
    cached_parent_mtime_ns = prior.parent_mtime_ns if prior is not None else 0
    dirs, parent_mtime_ns = discover_related_tool_artifact_dirs_cached(
        agent,
        artifacts_dir,
        cached_dirs=cached_dirs,
        cached_parent_mtime_ns=cached_parent_mtime_ns,
    )
    tool_call_paths = [directory / TOOL_CALLS_FILENAME for directory in dirs]
    current_mtime = _max_mtime_ns_for_paths(tool_call_paths)

    if prior is not None and current_mtime == prior.artifact_mtime_ns:
        prior.discovered_dirs = dirs
        prior.parent_mtime_ns = parent_mtime_ns
        prior.last_worker_monotonic = now_mono
        return prior.entries

    entries = _normalize_entries(read_tool_calls_for_agent(agent, artifact_dirs=dirs))
    _tools_cache[cache_key] = _ToolsCacheEntry(
        entries=entries,
        fetch_time=local_now(),
        artifact_mtime_ns=current_mtime,
        discovered_dirs=dirs,
        parent_mtime_ns=parent_mtime_ns,
        last_worker_monotonic=now_mono,
    )
    return entries


__all__ = [
    "ToolsCacheEntry",
    "cached_tool_calls_end_reference",
    "cached_tool_calls_have_pending",
    "fetch_tool_calls_cached",
    "get_cache_key",
    "invalidate_cached_tool_calls",
    "mark_tool_call_fetch_started",
    "peek_cached_tool_calls",
    "peek_tool_calls_cache_entry",
    "should_throttle_tool_call_fetch",
    "slow_tool_sources_have_pending",
    "tools_cache",
]

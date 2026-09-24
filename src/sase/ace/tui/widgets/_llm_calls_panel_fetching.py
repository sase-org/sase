"""Cache/source coordination helpers for the LLM Calls panel widget."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.llm_calls import build_cached_slow_tool_sources
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.llm_calls.cache import (
    invalidate_cached_tool_calls,
    mark_tool_call_fetch_started,
    peek_tool_calls_cache_entry,
    should_throttle_tool_call_fetch,
)


def cached_tool_call_count(agent: Agent) -> int | None:
    """Return the cached tool-call count without I/O, or None when cold."""
    from sase.ace.tui.llm_calls import supports_slow_tool_sources

    if supports_slow_tool_sources(agent):
        sources = build_cached_slow_tool_sources(agent)
        if sources is None:
            return None
        return sum(len(source.entries) for source in sources)
    entry = peek_tool_calls_cache_entry(agent)
    if entry is None:
        return None
    entries = entry.entries
    if entries is None:
        return 0
    return len(entries)


def latest_cached_fetch_time(agent: Agent) -> datetime | None:
    fetch_times = [
        cache_entry.fetch_time
        for row in (agent, *tuple(getattr(agent, "runtime_children", ())))
        if row is agent or row.is_agent_entry
        for cache_entry in (peek_tool_calls_cache_entry(row),)
        if cache_entry is not None
    ]
    return max(fetch_times) if fetch_times else None


def _source_cache_agents(agent: Agent) -> tuple[Agent, ...]:
    return (
        agent,
        *tuple(
            child
            for child in getattr(agent, "runtime_children", ())
            if child.is_agent_entry
        ),
    )


def should_throttle_tool_sources(agent: Agent) -> bool:
    return any(
        should_throttle_tool_call_fetch(row) for row in _source_cache_agents(agent)
    )


def mark_tool_source_fetch_started(agent: Agent) -> None:
    for row in _source_cache_agents(agent):
        mark_tool_call_fetch_started(row)


def invalidate_tool_source_caches(agent: Agent) -> None:
    for row in _source_cache_agents(agent):
        invalidate_cached_tool_calls(row)

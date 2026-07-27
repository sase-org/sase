"""Cached detail-header enrichment for the agent prompt panel."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.tools import (
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.ace.tui.widgets.file_panel._diff import DIFF_CACHE_TTL_SECONDS
from ...models.agent import Agent
from ...models.agent_associated_plan import (
    associated_plan_cache_key,
    resolve_agent_plan_enrichment,
)
from ...models.agent_bead import BEAD_DISPLAY_CACHE_MISS, cached_bead_display
from ...models.agent_wait_beads import resolve_wait_bead_statuses
from ._agent_display_state import DetailHeaderSummary
from ._helpers import load_xprompts_used


@dataclass(frozen=True)
class DetailHeaderSummaryCacheEntry:
    """Panel-local cached detail-header enrichment."""

    summary: DetailHeaderSummary
    cached_monotonic: float
    associated_plan_key: tuple[object, ...]


_DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES = 256


def _detail_header_summary_cache(
    widget: object,
) -> OrderedDict[tuple[Any, ...], DetailHeaderSummaryCacheEntry]:
    cache = getattr(widget, "_agent_detail_header_summary_cache", None)
    if cache is None:
        cache = OrderedDict()
        cast(Any, widget)._agent_detail_header_summary_cache = cache
    return cast(
        OrderedDict[tuple[Any, ...], DetailHeaderSummaryCacheEntry],
        cache,
    )


def get_cached_detail_header_summary(
    widget: object,
    agent: Agent,
) -> DetailHeaderSummary | None:
    """Return a cached detail-header summary for ``agent`` when available."""
    cache = _detail_header_summary_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return None
    if entry.associated_plan_key != associated_plan_cache_key(agent):
        del cache[agent.identity]
        return None
    cache.move_to_end(agent.identity)
    return entry.summary


def detail_header_summary_cache_key(
    widget: object,
    agent: Agent,
) -> tuple[object, ...] | None:
    """Return a panel-local key for the summary currently used by ``agent``.

    The summary object is replaced atomically when enrichment lands. Its
    identity therefore distinguishes cold, warm, and refreshed header inputs
    without attempting to hash the summary's list-valued fields.
    """
    summary = get_cached_detail_header_summary(widget, agent)
    if summary is None:
        return None
    return (agent.identity, id(summary))


def should_refresh_detail_header_summary(
    widget: object,
    agent: Agent,
) -> bool:
    """Return whether ``agent``'s cached detail-header summary is absent/stale."""
    cache = _detail_header_summary_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return True
    if entry.associated_plan_key != associated_plan_cache_key(agent):
        del cache[agent.identity]
        return True
    cache.move_to_end(agent.identity)
    return (time.monotonic() - entry.cached_monotonic) >= DIFF_CACHE_TTL_SECONDS


def cache_detail_header_summary(
    widget: object,
    agent: Agent,
    summary: DetailHeaderSummary,
) -> None:
    """Store ``summary`` in ``widget``'s bounded detail-header cache."""
    cache = _detail_header_summary_cache(widget)
    cache[agent.identity] = DetailHeaderSummaryCacheEntry(
        summary=summary,
        cached_monotonic=time.monotonic(),
        associated_plan_key=associated_plan_cache_key(agent),
    )
    cache.move_to_end(agent.identity)
    while len(cache) > _DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def clear_detail_header_summary_cache(widget: object) -> None:
    """Clear ``widget``'s detail-header enrichment cache if it exists."""
    cache = getattr(widget, "_agent_detail_header_summary_cache", None)
    if cache is not None:
        cache.clear()


def build_detail_header_summary(
    agent: Agent,
    *,
    include_slow_tools: bool = True,
) -> DetailHeaderSummary:
    """Build expensive header enrichments outside hot selection rendering.

    ``include_slow_tools`` lets clan aggregation reuse all existing context
    loaders without discovering tool-call artifacts unless that aggregate
    section was explicitly requested by the current fold state.
    """
    xprompts_used = None
    if agent.step_type not in ("bash", "python", "parallel"):
        xprompts_used = load_xprompts_used(agent)

    # Only confirmed bead displays surface in the header. A cache miss means
    # the candidate has not been confirmed against a bead store yet, so render
    # nothing here; the async worker resolves it off the event loop and the
    # header re-renders once a concrete issue is confirmed.
    bead_display = None
    if agent.agent_name:
        cached_display = cached_bead_display(agent)
        if cached_display is not BEAD_DISPLAY_CACHE_MISS:
            bead_display = cast(str | None, cached_display)

    plan_enrichment = resolve_agent_plan_enrichment(agent)
    associated_plan = plan_enrichment.associated_plan

    slow_tool_sources = None
    if include_slow_tools and supports_slow_tool_sources(agent):
        slow_tool_sources = build_slow_tool_sources(agent)

    from sase.ace.tui.memory_reads import load_memory_reads_for_agent_context
    from sase.ace.tui.opened_workspaces import (
        load_opened_workspaces_for_agent_context,
    )
    from sase.ace.tui.skill_uses import load_skill_uses_for_agent_context

    from ..file_panel._linked_deltas import get_cached_linked_delta_groups
    from ._artifact_files import artifact_file_paths as resolve_artifact_file_paths
    from ._agent_deltas import agent_commit_linked_delta_groups, agent_delta_entries

    linked_delta_groups = get_cached_linked_delta_groups(agent)
    if not linked_delta_groups:
        linked_delta_groups = agent_commit_linked_delta_groups(agent)

    resolved_artifact_file_paths = resolve_artifact_file_paths(agent)
    if plan_enrichment.resolved_plan_paths:
        plan_paths = {
            Path(path).resolve(strict=False)
            for path in plan_enrichment.resolved_plan_paths
        }
        resolved_artifact_file_paths = [
            artifact_file
            for artifact_file in resolved_artifact_file_paths
            if Path(artifact_file.actual_path).resolve(strict=False) not in plan_paths
        ]

    return DetailHeaderSummary(
        xprompts_used=xprompts_used,
        bead_display=bead_display,
        wait_bead_statuses=resolve_wait_bead_statuses(agent),
        phase_bead=plan_enrichment.phase_bead,
        associated_plan=associated_plan,
        delta_entries=agent_delta_entries(agent),
        linked_delta_groups=linked_delta_groups,
        artifact_file_paths=resolved_artifact_file_paths,
        memory_reads=load_memory_reads_for_agent_context(agent),
        skill_uses=load_skill_uses_for_agent_context(agent),
        opened_workspaces=load_opened_workspaces_for_agent_context(agent),
        slow_tool_sources=slow_tool_sources,
    )


def publish_opened_workspaces_cache(
    widget: object,
    agent: Agent,
    events: tuple[OpenedWorkspaceDisplayEvent, ...],
) -> None:
    """Hand off ``agent``'s opened-workspace events to the app (no I/O).

    The ``t`` keymap reads this in-memory cache to decide whether to open the
    tmux workspace chooser, so it never re-reads marker files on keypress.
    Resolving ``widget.app`` defensively keeps headless render stubs (which
    have no mounted app) working.
    """
    try:
        app = widget.app  # type: ignore[attr-defined]
    except (AttributeError, LookupError):
        return
    publisher = getattr(app, "publish_selected_agent_opened_workspaces", None)
    if callable(publisher):
        publisher(agent, events)

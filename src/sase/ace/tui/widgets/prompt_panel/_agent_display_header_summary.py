"""Cached detail-header enrichment for the agent prompt panel."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any, cast

from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.tools import (
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.widgets.file_panel._diff import DIFF_CACHE_TTL_SECONDS
from ...models.agent import Agent
from ...models.agent_page_url import agent_publishes_page, resolve_agent_page_url
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
HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS = 30.0

_DETAIL_HEADER_TRACE_SEEN_MAX_ENTRIES = 512
_detail_header_trace_seen: OrderedDict[tuple[object, ...], None] = OrderedDict()


def _detail_header_trace_cache_state(agent: Agent) -> str:
    """Best-effort cold/warm marker for the parent enrichment trace span.

    Process-local and telemetry-only: "cold" means this agent identity has
    not been resolved before in this process; "warm" means it has. This is
    coarser than (and independent of) the per-resolver caches exercised
    below it — it exists so a real-terminal trace capture can be read
    without cross-referencing every resolver's own cache state.
    """
    key = agent.identity
    seen = key in _detail_header_trace_seen
    _detail_header_trace_seen[key] = None
    _detail_header_trace_seen.move_to_end(key)
    while len(_detail_header_trace_seen) > _DETAIL_HEADER_TRACE_SEEN_MAX_ENTRIES:
        _detail_header_trace_seen.popitem(last=False)
    return "warm" if seen else "cold"


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

    Use a semantic digest rather than object identity so a periodic enrichment
    that returns the same header inputs does not invalidate the annotated hint
    document merely because the worker constructed a new dataclass instance.
    """
    summary = get_cached_detail_header_summary(widget, agent)
    if summary is None:
        return None
    encoded = repr(summary).encode("utf-8", errors="replace")
    summary_digest = blake2b(encoded, digest_size=16).hexdigest()
    return (agent.identity, summary_digest)


def _hint_detail_header_refresh_active(widget: object) -> bool:
    """Return whether the Agents detail is in an active file-hint session."""
    try:
        app = widget.app  # type: ignore[attr-defined]
    except (AttributeError, LookupError):
        return False
    return bool(
        getattr(app, "current_tab", None) == "agents"
        and getattr(app, "_hint_mode_active", False)
    )


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
    refresh_interval = (
        HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS
        if _hint_detail_header_refresh_active(widget)
        else DIFF_CACHE_TTL_SECONDS
    )
    return (time.monotonic() - entry.cached_monotonic) >= refresh_interval


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


_TRACE_SPAN_PREFIX = "widget.prompt_panel.build_detail_header_summary"


def build_detail_header_summary(
    agent: Agent,
    *,
    include_slow_tools: bool = True,
    include_agent_page_url: bool = True,
) -> DetailHeaderSummary:
    """Build expensive header enrichments outside hot selection rendering.

    The include flags let clan aggregation reuse existing context loaders
    without resolving per-member details that the aggregate does not render.

    Emits one parent ``tui_trace`` span plus one child span per resolver
    (bead sase-l6.1) so a real capture can attribute the enrichment cost to
    a specific lane; see ``docs/perf_runbook.md``. Free when
    ``SASE_TUI_TRACE`` is unset.
    """
    with tui_trace(
        _TRACE_SPAN_PREFIX,
        agent=agent.cl_name,
        cache_state=_detail_header_trace_cache_state(agent),
    ):
        return _build_detail_header_summary_impl(
            agent,
            include_slow_tools=include_slow_tools,
            include_agent_page_url=include_agent_page_url,
        )


def _build_detail_header_summary_impl(
    agent: Agent,
    *,
    include_slow_tools: bool,
    include_agent_page_url: bool,
) -> DetailHeaderSummary:
    xprompts_used = None
    if agent.step_type not in ("bash", "python", "parallel"):
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.xprompts_used"):
            xprompts_used = load_xprompts_used(agent)

    # Only confirmed bead displays surface in the header. A cache miss means
    # the candidate has not been confirmed against a bead store yet, so render
    # nothing here; the async worker resolves it off the event loop and the
    # header re-renders once a concrete issue is confirmed.
    bead_display = None
    if agent.agent_name:
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.bead_display"):
            cached_display = cached_bead_display(agent)
        if cached_display is not BEAD_DISPLAY_CACHE_MISS:
            bead_display = cast(str | None, cached_display)

    with tui_trace(f"{_TRACE_SPAN_PREFIX}.plan_enrichment"):
        plan_enrichment = resolve_agent_plan_enrichment(agent)
    associated_plan = plan_enrichment.associated_plan

    slow_tool_sources = None
    if include_slow_tools and supports_slow_tool_sources(agent):
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.slow_tool_sources"):
            slow_tool_sources = build_slow_tool_sources(agent)

    agent_page_url = None
    if include_agent_page_url and agent_publishes_page(agent):
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.agent_page_url"):
            agent_page_url = resolve_agent_page_url(agent)

    from sase.ace.tui.memory_reads import load_memory_reads_for_agent_context
    from sase.ace.tui.opened_workspaces import (
        load_opened_workspaces_for_agent_context,
    )
    from sase.ace.tui.skill_uses import load_skill_uses_for_agent_context

    from ..file_panel._linked_deltas import get_cached_linked_delta_groups
    from ._artifact_files import artifact_file_paths as resolve_artifact_file_paths
    from ._agent_deltas import agent_commit_linked_delta_groups, agent_delta_entries

    with tui_trace(f"{_TRACE_SPAN_PREFIX}.linked_delta_groups"):
        linked_delta_groups = get_cached_linked_delta_groups(agent)
        if not linked_delta_groups:
            linked_delta_groups = agent_commit_linked_delta_groups(agent)

    with tui_trace(f"{_TRACE_SPAN_PREFIX}.artifact_file_paths"):
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

    with tui_trace(f"{_TRACE_SPAN_PREFIX}.memory_reads"):
        memory_reads = load_memory_reads_for_agent_context(agent)
    with tui_trace(f"{_TRACE_SPAN_PREFIX}.skill_uses"):
        skill_uses = load_skill_uses_for_agent_context(agent)
    with tui_trace(f"{_TRACE_SPAN_PREFIX}.opened_workspaces"):
        opened_workspaces = load_opened_workspaces_for_agent_context(agent)
    with tui_trace(f"{_TRACE_SPAN_PREFIX}.delta_entries"):
        delta_entries = agent_delta_entries(agent)
    with tui_trace(f"{_TRACE_SPAN_PREFIX}.wait_bead_statuses"):
        wait_bead_statuses = resolve_wait_bead_statuses(agent)

    return DetailHeaderSummary(
        xprompts_used=xprompts_used,
        bead_display=bead_display,
        wait_bead_statuses=wait_bead_statuses,
        phase_bead=plan_enrichment.bead_summary,
        associated_plan=associated_plan,
        delta_entries=delta_entries,
        linked_delta_groups=linked_delta_groups,
        artifact_file_paths=resolved_artifact_file_paths,
        memory_reads=memory_reads,
        skill_uses=skill_uses,
        opened_workspaces=opened_workspaces,
        slow_tool_sources=slow_tool_sources,
        agent_page_url=agent_page_url,
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

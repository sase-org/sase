"""Cached detail-header enrichment for the agent prompt panel.

Per-lane freshness (bead sase-l6.3): ``tui_perf.md`` rule 10 says pollers
must revalidate cached snapshots on their existing tick rather than
recomputing on every one, and recompute only on a separate, much longer
cadence. The old blanket ``DIFF_CACHE_TTL_SECONDS`` (1 s) broke that rule by
expiring the *entire* summary on every repaint trigger (the 10 s auto-refresh,
the 5 s slow-tool tick, live-reply updates), so a stationary selection paid a
full twelve-resolver recompute on almost every one of those triggers. Each
lane below instead gets a cadence sized to what actually invalidates it:

- ``wait-beads``: derived only from data already loaded on the ``Agent`` row.
  Nothing about it changes between repaints of the same selection, so it gets
  no time-based TTL at all; only a new cache entry (a new selection, or a
  plan/bead identity change) re-resolves it.
- ``artifacts``, ``memory``, ``skills``, ``workspaces``, ``plan-bead``,
  ``xprompts``, ``page-url``: store- or lookup-backed but each already has
  (or gains, in the sibling `stores` phase) its own mtime-keyed cache, so a
  revalidation here is cheap. They share the auto-refresh cadence (10 s)
  instead of a sub-second one.
- ``slow-tools``: matched to its own 5 s render tick
  (``_configure_slow_tool_render_tick``) rather than either extreme, so it
  neither outruns the tick that consumes it nor falls back to the 1 s bug.

An active file-hint session still widens every lane to
``HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS`` so hint numbers stay stable
while the user is reading, exactly as the single blanket TTL used to.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from hashlib import blake2b
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.tools import (
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.ace.tui.util.trace import is_enabled as tui_trace_is_enabled
from sase.ace.tui.util.trace import tui_trace
from ...models.agent import Agent
from ...models.agent_page_url import agent_publishes_page, resolve_agent_page_url
from ...models.agent_associated_plan import (
    associated_plan_cache_key,
    resolve_agent_plan_enrichment,
)
from ...models.agent_bead import BEAD_DISPLAY_CACHE_MISS, cached_bead_display
from ...models.agent_wait_beads import resolve_wait_bead_statuses
from ._agent_display_state import (
    ALL_DETAIL_CONTEXT_LANES,
    DetailContextLane,
    DetailHeaderSummary,
)
from ._helpers import load_xprompts_used

if TYPE_CHECKING:
    from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
    from sase.ace.tui.skill_uses import SkillUseDisplayEvent

    from ..file_panel._linked_deltas import LinkedDeltaGroup


@dataclass(frozen=True)
class DetailHeaderSummaryCacheEntry:
    """Panel-local cached detail-header enrichment."""

    summary: DetailHeaderSummary
    cached_monotonic: float
    associated_plan_key: tuple[object, ...]


_DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES = 256
HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS = 30.0

# No lane keeps the old 1 s blanket cadence; see the module docstring for why
# each lane below gets the cadence it gets.
_LANE_NO_TTL_SECONDS = float("inf")
_LANE_DEFAULT_REFRESH_INTERVAL_SECONDS = 10.0
_LANE_SLOW_TOOLS_REFRESH_INTERVAL_SECONDS = 5.0
_LANE_REFRESH_INTERVAL_SECONDS: dict[DetailContextLane, float] = {
    "wait-beads": _LANE_NO_TTL_SECONDS,
    "slow-tools": _LANE_SLOW_TOOLS_REFRESH_INTERVAL_SECONDS,
    "plan-bead": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "artifacts": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "memory": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "skills": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "workspaces": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "xprompts": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "page-url": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
}

# Fields on `DetailHeaderSummary` that belong to each resolution lane, used to
# merge a partial rebuild into a previously cached summary without losing the
# lanes the partial rebuild did not touch. `bead_display` is intentionally
# absent: it is not a lane (see the module docstring) and always takes the
# incoming value.
_LANE_FIELDS: dict[DetailContextLane, tuple[str, ...]] = {
    "plan-bead": ("associated_plan", "phase_bead"),
    "artifacts": ("artifact_file_paths", "delta_entries", "linked_delta_groups"),
    "memory": ("memory_reads",),
    "skills": ("skill_uses",),
    "workspaces": ("opened_workspaces",),
    "slow-tools": ("slow_tool_sources",),
    "xprompts": ("xprompts_used",),
    "page-url": ("agent_page_url",),
    "wait-beads": ("wait_bead_statuses",),
}

# Cheapest-first resolution batches for the streaming worker (bead
# sase-l6.4), derived from the bead sase-l6 trace baseline
# (plans/202608/sase_context_incremental.md). Batch 1 lanes measure ~0 ms
# even cold: `wait-beads` is derived from data already on the `Agent` row,
# `plan-bead` hits `_PLAN_ASSOCIATION_CACHE`, `workspaces` stats marker
# files instead of parsing a log, and `xprompts`/`page-url` are cheap
# lookups. Batch 2 lanes each parse a multi-MB append-only store on a
# cache miss (~85-210 ms cold per the trace table; near-zero once the
# sibling `stores` phase's snapshot caches are warm) -- still slower than
# batch 1, so they publish separately instead of blocking it. Batch 3
# (`slow-tools`) is pinned to its own 5 s render-tick cadence
# (`_LANE_SLOW_TOOLS_REFRESH_INTERVAL_SECONDS`) and must never block the
# lanes ahead of it. Every `DetailContextLane` appears in exactly one
# batch; see `test_lane_resolution_batches_cover_every_lane_exactly_once`.
LANE_RESOLUTION_BATCHES: tuple[frozenset[DetailContextLane], ...] = (
    frozenset({"wait-beads", "plan-bead", "workspaces", "xprompts", "page-url"}),
    frozenset({"artifacts", "memory", "skills"}),
    frozenset({"slow-tools"}),
)

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


def _effective_lane_refresh_interval(
    lane: DetailContextLane,
    *,
    hint_active: bool,
) -> float:
    interval = _LANE_REFRESH_INTERVAL_SECONDS[lane]
    if hint_active:
        return max(interval, HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS)
    return interval


def should_refresh_detail_header_summary(
    widget: object,
    agent: Agent,
) -> frozenset[DetailContextLane]:
    """Return the absent/stale lanes of ``agent``'s cached detail-header summary.

    An empty result means the cached summary is fully fresh and no rebuild is
    needed at all.
    """
    cache = _detail_header_summary_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return ALL_DETAIL_CONTEXT_LANES
    if entry.associated_plan_key != associated_plan_cache_key(agent):
        del cache[agent.identity]
        return ALL_DETAIL_CONTEXT_LANES
    cache.move_to_end(agent.identity)
    hint_active = _hint_detail_header_refresh_active(widget)
    elapsed = time.monotonic() - entry.cached_monotonic
    stale_lanes = {
        lane
        for lane in ALL_DETAIL_CONTEXT_LANES
        if lane not in entry.summary.ready_lanes
        or elapsed >= _effective_lane_refresh_interval(lane, hint_active=hint_active)
    }
    return frozenset(stale_lanes)


def merge_detail_header_summary_lanes(
    previous: DetailHeaderSummary,
    incoming: DetailHeaderSummary,
) -> DetailHeaderSummary:
    """Merge ``incoming``'s newly resolved lanes into ``previous``.

    Lanes ``previous`` had ready that ``incoming`` did not (re)resolve keep
    their previously cached values; every other field takes ``incoming``'s
    value, including fields that are not lane-gated (``bead_display``).
    Public (bead sase-l6.4) so the streaming worker can fold each cheapest-
    first batch into a running summary in-thread, independent of the
    widget-cache merge below.
    """
    kept_lanes = previous.ready_lanes - incoming.ready_lanes
    if not kept_lanes:
        return incoming
    overrides: dict[str, Any] = {
        field_name: getattr(previous, field_name)
        for lane in kept_lanes
        for field_name in _LANE_FIELDS[lane]
    }
    overrides["ready_lanes"] = previous.ready_lanes | incoming.ready_lanes
    return replace(incoming, **overrides)


def immediate_detail_header_summary(
    widget: object,
    agent: Agent,
) -> DetailHeaderSummary:
    """Zero-I/O summary for the pre-debounce immediate paint (bead sase-l6.5).

    Starts from whatever is already cached for ``agent``, so a lane a prior
    selection or a completed background enrichment already resolved renders
    immediately. On top of that, forces the ``artifacts`` lane ready even
    when nothing is cached yet: ``append_agent_artifacts_lane`` derives its
    commit rows from ``agent_commit_groups``, which parses only in-memory
    ``step_output`` metadata (0.0 ms per the bead sase-l6 trace baseline, no
    disk I/O), so showing it before the debounced worker has resolved the
    lane's delta/artifact-file data is legal under
    ``sase/memory/tui_perf.md`` rule 11. The result is never written back to
    the widget's summary cache: doing so would tell
    ``should_refresh_detail_header_summary`` that ``artifacts`` is already
    fresh and delay the real resolution of the delta and artifact-file data
    this synthesized lane omits.
    """
    cached = get_cached_detail_header_summary(widget, agent)
    base = (
        cached if cached is not None else DetailHeaderSummary(ready_lanes=frozenset())
    )
    if "artifacts" in base.ready_lanes:
        return base
    return merge_detail_header_summary_lanes(
        base, DetailHeaderSummary(ready_lanes=frozenset({"artifacts"}))
    )


def detail_header_summary_is_complete(summary: DetailHeaderSummary | None) -> bool:
    """Return whether every SASE CONTEXT lane has been attempted at least once.

    A ``None`` summary (nothing cached yet) counts as incomplete. Used to
    decide whether a streamed, partially-resolved summary is safe to treat
    as "done" -- e.g. to allow a hint-mode document to rebuild even while
    the hint input has a typed value (bead sase-l6.4).
    """
    return summary is not None and summary.ready_lanes >= ALL_DETAIL_CONTEXT_LANES


def cache_detail_header_summary(
    widget: object,
    agent: Agent,
    summary: DetailHeaderSummary,
) -> None:
    """Merge ``summary``'s resolved lanes into ``widget``'s bounded cache."""
    cache = _detail_header_summary_cache(widget)
    current_plan_key = associated_plan_cache_key(agent)
    previous_entry = cache.get(agent.identity)
    merged = summary
    if previous_entry is not None and previous_entry.associated_plan_key == (
        current_plan_key
    ):
        merged = merge_detail_header_summary_lanes(previous_entry.summary, summary)
    cache[agent.identity] = DetailHeaderSummaryCacheEntry(
        summary=merged,
        cached_monotonic=time.monotonic(),
        associated_plan_key=current_plan_key,
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
    lanes: frozenset[DetailContextLane] | None = None,
) -> DetailHeaderSummary:
    """Build expensive header enrichments outside hot selection rendering.

    ``lanes`` selects which of the independently resolved SASE CONTEXT lanes
    (and non-context summary fields) to build; omitting it resolves every
    lane, which is what most callers need. A caller that only renders some
    lanes -- the clan aggregation snapshot below, and eventually the
    streaming per-lane worker -- passes a narrower set instead of paying for
    the rest. The returned summary's ``ready_lanes`` echoes back exactly the
    lanes that were resolved.

    Emits one parent ``tui_trace`` span plus one child span per resolver
    (bead sase-l6.1) so a real capture can attribute the enrichment cost to
    a specific lane; see ``docs/perf_runbook.md``. Free when
    ``SASE_TUI_TRACE`` is unset.
    """
    resolved_lanes = ALL_DETAIL_CONTEXT_LANES if lanes is None else lanes
    trace_fields: dict[str, object] = {"agent": agent.cl_name}
    if tui_trace_is_enabled():
        trace_fields["cache_state"] = _detail_header_trace_cache_state(agent)
    with tui_trace(_TRACE_SPAN_PREFIX, **trace_fields):
        return _build_detail_header_summary_impl(agent, lanes=resolved_lanes)


def _build_detail_header_summary_impl(
    agent: Agent,
    *,
    lanes: frozenset[DetailContextLane],
) -> DetailHeaderSummary:
    xprompts_used = None
    if "xprompts" in lanes and agent.step_type not in ("bash", "python", "parallel"):
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.xprompts_used"):
            xprompts_used = load_xprompts_used(agent)

    # Only confirmed bead displays surface in the header. A cache miss means
    # the candidate has not been confirmed against a bead store yet, so render
    # nothing here; the async worker resolves it off the event loop and the
    # header re-renders once a concrete issue is confirmed. This is a cheap
    # cache read, not a lane: it always runs regardless of ``lanes``.
    bead_display = None
    if agent.agent_name:
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.bead_display"):
            cached_display = cached_bead_display(agent)
        if cached_display is not BEAD_DISPLAY_CACHE_MISS:
            bead_display = cast(str | None, cached_display)

    # The `artifacts` lane filters plan-authored paths out of its file list,
    # so it needs the plan-bead resolver even when the `plan-bead` lane
    # itself was not requested. Only surface `associated_plan`/`phase_bead`
    # when `plan-bead` is actually a requested lane.
    plan_enrichment = None
    if "plan-bead" in lanes or "artifacts" in lanes:
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.plan_enrichment"):
            plan_enrichment = resolve_agent_plan_enrichment(agent)
    associated_plan = None
    phase_bead = None
    if plan_enrichment is not None and "plan-bead" in lanes:
        associated_plan = plan_enrichment.associated_plan
        phase_bead = plan_enrichment.bead_summary

    slow_tool_sources = None
    if "slow-tools" in lanes and supports_slow_tool_sources(agent):
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.slow_tool_sources"):
            slow_tool_sources = build_slow_tool_sources(agent)

    agent_page_url = None
    if "page-url" in lanes and agent_publishes_page(agent):
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.agent_page_url"):
            agent_page_url = resolve_agent_page_url(agent)

    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = ()
    resolved_artifact_file_paths = None
    delta_entries = None
    if "artifacts" in lanes:
        from ..file_panel._linked_deltas import get_cached_linked_delta_groups
        from ._artifact_files import (
            artifact_file_paths as resolve_artifact_file_paths,
        )
        from ._agent_deltas import (
            agent_commit_linked_delta_groups,
            agent_delta_entries,
        )

        with tui_trace(f"{_TRACE_SPAN_PREFIX}.linked_delta_groups"):
            linked_delta_groups = get_cached_linked_delta_groups(agent)
            if not linked_delta_groups:
                linked_delta_groups = agent_commit_linked_delta_groups(agent)

        with tui_trace(f"{_TRACE_SPAN_PREFIX}.artifact_file_paths"):
            resolved_artifact_file_paths = resolve_artifact_file_paths(agent)
        if plan_enrichment is not None and plan_enrichment.resolved_plan_paths:
            plan_paths = {
                Path(path).resolve(strict=False)
                for path in plan_enrichment.resolved_plan_paths
            }
            resolved_artifact_file_paths = [
                artifact_file
                for artifact_file in resolved_artifact_file_paths
                if Path(artifact_file.actual_path).resolve(strict=False)
                not in plan_paths
            ]

        with tui_trace(f"{_TRACE_SPAN_PREFIX}.delta_entries"):
            delta_entries = agent_delta_entries(agent)

    memory_reads: tuple[MemoryReadDisplayEvent, ...] = ()
    if "memory" in lanes:
        from sase.ace.tui.memory_reads import load_memory_reads_for_agent_context

        with tui_trace(f"{_TRACE_SPAN_PREFIX}.memory_reads"):
            memory_reads = load_memory_reads_for_agent_context(agent)

    skill_uses: tuple[SkillUseDisplayEvent, ...] = ()
    if "skills" in lanes:
        from sase.ace.tui.skill_uses import load_skill_uses_for_agent_context

        with tui_trace(f"{_TRACE_SPAN_PREFIX}.skill_uses"):
            skill_uses = load_skill_uses_for_agent_context(agent)

    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = ()
    if "workspaces" in lanes:
        from sase.ace.tui.opened_workspaces import (
            load_opened_workspaces_for_agent_context,
        )

        with tui_trace(f"{_TRACE_SPAN_PREFIX}.opened_workspaces"):
            opened_workspaces = load_opened_workspaces_for_agent_context(agent)

    wait_bead_statuses = None
    if "wait-beads" in lanes:
        with tui_trace(f"{_TRACE_SPAN_PREFIX}.wait_bead_statuses"):
            wait_bead_statuses = resolve_wait_bead_statuses(agent)

    return DetailHeaderSummary(
        xprompts_used=xprompts_used,
        bead_display=bead_display,
        wait_bead_statuses=wait_bead_statuses,
        phase_bead=phase_bead,
        associated_plan=associated_plan,
        delta_entries=delta_entries,
        linked_delta_groups=linked_delta_groups,
        artifact_file_paths=resolved_artifact_file_paths,
        memory_reads=memory_reads,
        skill_uses=skill_uses,
        opened_workspaces=opened_workspaces,
        slow_tool_sources=slow_tool_sources,
        agent_page_url=agent_page_url,
        ready_lanes=lanes,
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

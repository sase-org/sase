"""Panel-local cache and freshness policy for detail-header summaries."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from hashlib import blake2b
from typing import Any, cast

from ...models.agent import Agent
from ...models.agent_associated_plan import associated_plan_cache_key
from ._agent_display_state import (
    ALL_DETAIL_CONTEXT_LANES,
    DetailContextLane,
    DetailHeaderSummary,
)


@dataclass(frozen=True)
class DetailHeaderSummaryCacheEntry:
    """Panel-local cached detail-header enrichment."""

    summary: DetailHeaderSummary
    cached_monotonic: float
    associated_plan_key: tuple[object, ...]


DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES = 256
HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS = 30.0

# No lane keeps the old 1 s blanket cadence; see the module docstring for why
# each lane below gets the cadence it gets.
_LANE_NO_TTL_SECONDS = float("inf")
_LANE_DEFAULT_REFRESH_INTERVAL_SECONDS = 10.0
_LANE_SLOW_TOOLS_REFRESH_INTERVAL_SECONDS = 5.0
_LANE_REFRESH_INTERVAL_SECONDS: dict[DetailContextLane, float] = {
    "wait-beads": _LANE_NO_TTL_SECONDS,
    "slow-tools": _LANE_SLOW_TOOLS_REFRESH_INTERVAL_SECONDS,
    "tool-runs": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "plan-bead": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "artifacts": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "memory": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "glossary": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "skills": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "workspaces": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "macros": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
    "page-url": _LANE_DEFAULT_REFRESH_INTERVAL_SECONDS,
}

# Fields on `DetailHeaderSummary` that belong to each resolution lane, used to
# merge a partial rebuild into a previously cached summary without losing the
# lanes the partial rebuild did not touch. `bead_display` is intentionally
# absent: it is not a lane (see the module docstring) and always takes the
# incoming value.
_LANE_FIELDS: dict[DetailContextLane, tuple[str, ...]] = {
    "plan-bead": ("associated_plan", "phase_bead"),
    "artifacts": (
        "artifact_file_paths",
        "delta_entries",
        "linked_delta_groups",
        "artifact_reads",
        "bead_touch_entries",
    ),
    "memory": (
        "memory_reads",
        "memory_version_chips",
        "memory_version_pins",
        "memory_launch_row",
        "memory_launch_pin",
    ),
    "glossary": ("glossary_reads",),
    "skills": ("skill_uses",),
    "workspaces": ("opened_workspaces",),
    "slow-tools": ("slow_tool_sources",),
    "tool-runs": ("tool_run_summary",),
    "macros": ("macros_used",),
    "page-url": ("agent_page_url",),
    "wait-beads": ("wait_bead_statuses",),
}

# Cheapest-first resolution batches for the streaming worker (bead
# sase-l6.4), derived from the bead sase-l6 trace baseline
# (plans/202608/sase_context_incremental.md). Batch 1 lanes measure ~0 ms
# even cold: `wait-beads` is derived from data already on the `Agent` row,
# `plan-bead` hits `_PLAN_ASSOCIATION_CACHE`, `workspaces` stats marker
# files instead of parsing a log, and `macros`/`page-url` are cheap
# lookups. Batch 2 lanes each parse a multi-MB append-only store on a
# cache miss (~85-210 ms cold per the trace table; near-zero once the
# sibling `stores` phase's snapshot caches are warm) -- still slower than
# batch 1, so they publish separately instead of blocking it. Batch 3
# (`slow-tools`) is pinned to its own 5 s render-tick cadence
# (`_LANE_SLOW_TOOLS_REFRESH_INTERVAL_SECONDS`) and must never block the
# lanes ahead of it. `tool-runs` joins batch 1: an LRU hit costs ~0 ms and
# a miss is one lean indexed SQLite read on the worker thread, so it never
# blocks the lanes around it. Every `DetailContextLane` appears in exactly
# one batch; see
# `test_lane_resolution_batches_cover_every_lane_exactly_once`.
LANE_RESOLUTION_BATCHES: tuple[frozenset[DetailContextLane], ...] = (
    frozenset(
        {"wait-beads", "plan-bead", "workspaces", "macros", "page-url", "tool-runs"}
    ),
    frozenset({"artifacts", "memory", "glossary", "skills"}),
    frozenset({"slow-tools"}),
)


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
    while len(cache) > DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def clear_detail_header_summary_cache(widget: object) -> None:
    """Clear ``widget``'s detail-header enrichment cache if it exists."""
    cache = getattr(widget, "_agent_detail_header_summary_cache", None)
    if cache is not None:
        cache.clear()

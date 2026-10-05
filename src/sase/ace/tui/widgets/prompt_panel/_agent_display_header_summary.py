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
- ``artifacts``, ``memory``, ``glossary``, ``skills``, ``workspaces``,
  ``plan-bead``, ``macros``, ``page-url``: store- or lookup-backed but each already has
  (or gains, in the sibling `stores` phase) its own mtime-keyed cache, so a
  revalidation here is cheap. They share the auto-refresh cadence (10 s)
  instead of a sub-second one.
- ``tool-runs``: one lean indexed SQLite read behind a 64-entry LRU keyed
  by ``(selector key, store token)``, so a reload with an unchanged token
  costs ~0 ms. It shares the auto-refresh cadence (10 s); live movement
  between reloads comes from the in-memory glance overlay, not a new tick.
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
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.llm_calls import (
    build_slow_tool_sources,
    supports_slow_tool_sources,
)
from sase.ace.tui.util.trace import is_enabled as tui_trace_is_enabled
from sase.ace.tui.util.trace import tui_trace
from ...models.agent import Agent
from ...models.agent_page_url import agent_publishes_page, resolve_agent_page_url
from ...models.agent_associated_plan import resolve_agent_plan_enrichment
from ...models.agent_bead import BEAD_DISPLAY_CACHE_MISS, cached_bead_display
from ...models.agent_wait_beads import resolve_wait_bead_statuses
from ._agent_display_state import (
    ALL_DETAIL_CONTEXT_LANES,
    DetailContextLane,
    DetailHeaderSummary,
)
from ._helpers import load_macros_used
from ._agent_display_header_summary_cache import (
    DETAIL_HEADER_SUMMARY_CACHE_MAX_ENTRIES,
    HINT_DETAIL_HEADER_REFRESH_INTERVAL_SECONDS,
    LANE_RESOLUTION_BATCHES,
    DetailHeaderSummaryCacheEntry,
    cache_detail_header_summary,
    clear_detail_header_summary_cache,
    detail_header_summary_cache_key,
    detail_header_summary_is_complete,
    get_cached_detail_header_summary,
    immediate_detail_header_summary,
    merge_detail_header_summary_lanes,
    should_refresh_detail_header_summary,
)
from ._agent_display_header_memory_versions import enrich_memory_versions

if TYPE_CHECKING:
    from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
    from sase.ace.tui.bead_touches import BeadTouchEntry
    from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
    from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
    from sase.ace.tui.skill_uses import SkillUseDisplayEvent

    from ..file_panel._linked_deltas import LinkedDeltaGroup


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


DETAIL_HEADER_TRACE_SPAN_PREFIX = "widget.prompt_panel.build_detail_header_summary"


def _assigned_bead_titles(
    agent: Agent,
    phase_bead: object | None,
    associated_plan: object | None,
) -> dict[str, str]:
    """Return in-memory titles for the agent's assigned beads, if known.

    Only already-resolved summaries feed this map (the phase bead summary,
    the associated plan's epic/phase titles); it performs no store or
    index read so the UI thread stays off I/O. The merge uses it solely
    to title assignment-only rows.
    """
    titles: dict[str, str] = {}
    bead_summary = phase_bead
    bead_id = getattr(bead_summary, "id", None)
    bead_title = getattr(bead_summary, "title", None)
    if isinstance(bead_id, str) and bead_id.strip():
        if isinstance(bead_title, str) and bead_title.strip():
            titles[bead_id.strip()] = bead_title.strip()
    plan_title = getattr(associated_plan, "title", None)
    epic_bead_id = getattr(agent, "epic_bead_id", None)
    if (
        isinstance(epic_bead_id, str)
        and epic_bead_id.strip()
        and isinstance(plan_title, str)
        and plan_title.strip()
    ):
        titles.setdefault(epic_bead_id.strip(), plan_title.strip())
    phases = getattr(associated_plan, "phases", None)
    if phases:
        try:
            iterator = iter(phases)
        except TypeError:
            iterator = iter(())
        for phase in iterator:
            phase_id = getattr(phase, "id", None)
            phase_title = getattr(phase, "title", None)
            if (
                isinstance(phase_id, str)
                and phase_id.strip()
                and isinstance(phase_title, str)
                and phase_title.strip()
            ):
                titles.setdefault(phase_id.strip(), phase_title.strip())
    return titles


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
    with tui_trace(DETAIL_HEADER_TRACE_SPAN_PREFIX, **trace_fields):
        return _build_detail_header_summary_impl(agent, lanes=resolved_lanes)


def _build_detail_header_summary_impl(
    agent: Agent,
    *,
    lanes: frozenset[DetailContextLane],
) -> DetailHeaderSummary:
    macros_used = None
    if "macros" in lanes and agent.step_type not in ("bash", "python", "parallel"):
        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.macros_used"):
            macros_used = load_macros_used(agent)

    # Only confirmed bead displays surface in the header. A cache miss means
    # the candidate has not been confirmed against a bead store yet, so render
    # nothing here; the async worker resolves it off the event loop and the
    # header re-renders once a concrete issue is confirmed. This is a cheap
    # cache read, not a lane: it always runs regardless of ``lanes``.
    bead_display = None
    if agent.agent_name:
        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.bead_display"):
            cached_display = cached_bead_display(agent)
        if cached_display is not BEAD_DISPLAY_CACHE_MISS:
            bead_display = cast(str | None, cached_display)

    # The `artifacts` lane filters plan-authored paths out of its file list,
    # so it needs the plan-bead resolver even when the `plan-bead` lane
    # itself was not requested. Only surface `associated_plan`/`phase_bead`
    # when `plan-bead` is actually a requested lane.
    plan_enrichment = None
    if "plan-bead" in lanes or "artifacts" in lanes:
        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.plan_enrichment"):
            plan_enrichment = resolve_agent_plan_enrichment(agent)
    associated_plan = None
    phase_bead = None
    if plan_enrichment is not None and "plan-bead" in lanes:
        associated_plan = plan_enrichment.associated_plan
        phase_bead = plan_enrichment.bead_summary

    slow_tool_sources = None
    if "slow-tools" in lanes and supports_slow_tool_sources(agent):
        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.slow_tool_sources"):
            slow_tool_sources = build_slow_tool_sources(agent)

    tool_run_summary = None
    if "tool-runs" in lanes:
        from sase.ace.tui.tool_runs.summaries import resolve_tool_run_summary

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.tool_run_summary"):
            tool_run_summary = resolve_tool_run_summary(agent)

    agent_page_url = None
    if "page-url" in lanes and agent_publishes_page(agent):
        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.agent_page_url"):
            agent_page_url = resolve_agent_page_url(agent)

    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = ()
    resolved_artifact_file_paths = None
    delta_entries = None
    artifact_reads: tuple[ArtifactReadDisplayEvent, ...] = ()
    bead_touch_entries: tuple[BeadTouchEntry, ...] = ()
    if "artifacts" in lanes:
        from ..file_panel._linked_deltas import get_cached_linked_delta_groups
        from ._artifact_files import (
            artifact_file_paths as resolve_artifact_file_paths,
        )
        from ._agent_deltas import (
            agent_commit_linked_delta_groups,
            agent_delta_entries,
        )

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.linked_delta_groups"):
            linked_delta_groups = get_cached_linked_delta_groups(agent)
            if not linked_delta_groups:
                linked_delta_groups = agent_commit_linked_delta_groups(agent)

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.artifact_file_paths"):
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

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.delta_entries"):
            delta_entries = agent_delta_entries(agent)

        from sase.ace.tui.artifact_reads import load_artifact_reads_for_agent_context

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.artifact_reads"):
            artifact_reads = load_artifact_reads_for_agent_context(agent)

        from sase.ace.tui.bead_touches import (
            load_bead_touches_for_agent_context,
            merge_bead_touch_entries,
            own_bead_ids_for_agent,
        )

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.bead_touches"):
            bead_touch_entries = merge_bead_touch_entries(
                load_bead_touches_for_agent_context(agent),
                artifact_reads,
                own_bead_ids_for_agent(agent),
                _assigned_bead_titles(agent, phase_bead, associated_plan),
            )

    memory_reads: tuple[MemoryReadDisplayEvent, ...] = ()
    if "memory" in lanes:
        from sase.ace.tui.memory_reads import load_memory_reads_for_agent_context

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.memory_reads"):
            memory_reads = load_memory_reads_for_agent_context(agent)

    glossary_reads: tuple[GlossaryReadDisplayEvent, ...] = ()
    if "glossary" in lanes:
        from sase.ace.tui.glossary_reads import load_glossary_reads_for_agent_context

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.glossary_reads"):
            glossary_reads = load_glossary_reads_for_agent_context(agent)

    skill_uses: tuple[SkillUseDisplayEvent, ...] = ()
    if "skills" in lanes:
        from sase.ace.tui.skill_uses import load_skill_uses_for_agent_context

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.skill_uses"):
            skill_uses = load_skill_uses_for_agent_context(agent)

    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = ()
    if "workspaces" in lanes:
        from sase.ace.tui.opened_workspaces import (
            load_opened_workspaces_for_agent_context,
        )

        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.opened_workspaces"):
            opened_workspaces = load_opened_workspaces_for_agent_context(agent)

    wait_bead_statuses = None
    if "wait-beads" in lanes:
        with tui_trace(f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.wait_bead_statuses"):
            wait_bead_statuses = resolve_wait_bead_statuses(agent)

    return DetailHeaderSummary(
        macros_used=macros_used,
        bead_display=bead_display,
        wait_bead_statuses=wait_bead_statuses,
        phase_bead=phase_bead,
        associated_plan=associated_plan,
        delta_entries=delta_entries,
        linked_delta_groups=linked_delta_groups,
        artifact_file_paths=resolved_artifact_file_paths,
        artifact_reads=artifact_reads,
        bead_touch_entries=bead_touch_entries,
        memory_reads=memory_reads,
        glossary_reads=glossary_reads,
        skill_uses=skill_uses,
        opened_workspaces=opened_workspaces,
        slow_tool_sources=slow_tool_sources,
        tool_run_summary=tool_run_summary,
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

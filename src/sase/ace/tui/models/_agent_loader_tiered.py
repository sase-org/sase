"""Tiered TUI loads and public agent-loader entry points."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import time

from sase.core.agent_scan_wire import AgentArtifactScanWire

from ..util.trace import tui_trace
from ...hooks.processes import is_process_running
from ...patch import Patch
from ._agent_loader_artifact_config import PLAN_LIVE_SCAN_OPTIONS
from ._agent_loader_artifacts import (
    AgentLoadState,
    artifact_delta_load_state,
    artifact_dirs_for_normalized_timestamps as _artifact_dirs_for_timestamps,
    load_state_keeps_displayed_roster,
    normalize_timestamps as _normalize_artifact_timestamps,
    prepare_artifact_delta_paths,
    update_artifact_index_from_delta,
)
from ._agent_loader_normalization import (
    mark_live_artifact_delta_runners as _mark_delta_runners_live,
    normalize_live_plan_agents as _normalize_plan_agents,
    normalize_loaded_agents as _normalize_agents,
)
from ._agent_loader_scans import (
    artifact_snapshot_for_live_plan_load,
    artifact_snapshot_for_tui_load,
    scan_artifact_dirs_for_loader,
)
from ._agent_loader_sources import (
    load_agents_from_all_sources,
    load_agents_from_artifact_snapshot_sources,
    load_plan_agents_from_artifact_snapshot,
)
from ._loaders import (
    get_all_project_files,
    load_agents_from_running_field,
    load_workflow_states,
)
from ._timestamps import normalize_to_14_digit
from .agent import Agent
from .workflow import WorkflowEntry


@dataclass(frozen=True)
class _AgentLoadResult:
    """Agents plus metadata about the artifact-history tier used."""

    agents: list[Agent]
    workflow_agent_steps: list[Agent]
    state: AgentLoadState
    #: Always-on ``perf_counter`` timings for the ``index`` and ``decode``
    #: loader substages, in seconds. The remaining substages
    #: (``dismissed_snapshot``, ``provider``, ``projections``) are timed by
    #: the TUI disk-load wrapper, which merges them for telemetry.
    substages: dict[str, float] = field(default_factory=dict)


def normalize_timestamps(timestamps: Iterable[str]) -> set[str]:
    return _normalize_artifact_timestamps(timestamps)


def artifact_dirs_for_normalized_timestamps(normalized: set[str]) -> list[Path]:
    return _artifact_dirs_for_timestamps(normalized)


def load_all_workflows() -> list[WorkflowEntry]:
    """Load all workflow entries from workflow_state.json files.

    Returns:
        List of WorkflowEntry objects sorted by start time (most recent first).
    """
    workflows = load_workflow_states()

    # Sort by start time (most recent first)
    workflows_with_time = [w for w in workflows if w.start_time is not None]
    workflows_without_time = [w for w in workflows if w.start_time is None]

    workflows_with_time.sort(key=lambda w: w.start_time, reverse=True)  # type: ignore

    return workflows_with_time + workflows_without_time


def _load_agents_with_load_state(
    *,
    patch_snapshot: list[Patch] | None = None,
    full_history: bool = False,
    use_artifact_index: bool = True,
    index_freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    allow_lock_busy_source_scan: bool = True,
) -> _AgentLoadResult:
    """Load agents for the TUI and report whether history is complete."""

    index_start = time.perf_counter()
    with tui_trace(
        "agents.load_from_disk.index",
        index_freshness=index_freshness,
    ) as extra:
        artifact_snapshot, state = artifact_snapshot_for_tui_load(
            full_history=full_history,
            use_artifact_index=use_artifact_index,
            index_freshness=index_freshness,
            requested_limit=requested_limit,
            candidate_filter=candidate_filter,
            allow_lock_busy_source_scan=allow_lock_busy_source_scan,
        )
        extra["artifact_source"] = state.artifact_source
        extra["record_count"] = state.record_count
        extra["used_artifact_index"] = state.used_artifact_index
    index_elapsed = time.perf_counter() - index_start
    if load_state_keeps_displayed_roster(state):
        return _AgentLoadResult(
            agents=[],
            workflow_agent_steps=[],
            state=state,
            substages={"index": index_elapsed, "decode": 0.0},
        )
    decode_start = time.perf_counter()
    with tui_trace("agents.load_from_disk.decode") as extra:
        agents, workflow_agent_steps = load_agents_from_all_sources(
            patch_snapshot=patch_snapshot,
            artifact_snapshot=artifact_snapshot,
        )
        extra["decoded_count"] = len(agents) + len(workflow_agent_steps)
    decode_elapsed = time.perf_counter() - decode_start
    # This path always scans the RUNNING field via `load_agents_from_all_sources`,
    # so the roster is authoritative for workspace claims. The keeps-displayed
    # roster short-circuit above returns early without scanning, leaving the
    # default False. Bounded-prefix truncation is handled in `load_tiered_agents`,
    # which clears the flag when it slices the decoded roster to the viewport cap
    # (claim rows sort anywhere in that order and could have been cut).
    state = replace(state, running_claims_scanned=True)
    return _AgentLoadResult(
        agents=agents,
        workflow_agent_steps=workflow_agent_steps,
        state=state,
        substages={"index": index_elapsed, "decode": decode_elapsed},
    )


def _normalize_loaded_agents(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
    *,
    keep_orphaned_followups: bool = False,
) -> list[Agent]:
    normalized = _normalize_agents(
        agents,
        workflow_agent_steps,
        is_process_running=is_process_running,
        keep_orphaned_followups=keep_orphaned_followups,
    )
    from .agent_hijack_presentation import apply_hijack_ledger_presentation

    apply_hijack_ledger_presentation(normalized)
    return normalized


def _mark_live_artifact_delta_runners(agents: list[Agent]) -> None:
    """Attach bounded PID liveness proof to exact-delta rows.

    Artifact deltas intentionally do not rescan ProjectSpec RUNNING claims.
    Rechecking only the PIDs already present in the exact delta keeps the
    worker-side operation bounded while preventing a stale retry marker from
    reviving a dead terminal row.
    """
    _mark_delta_runners_live(
        agents,
        is_process_running=is_process_running,
    )


def _normalize_live_plan_agents(agents: list[Agent]) -> list[Agent]:
    """Normalize the cheap visibility-affecting pieces for plan-list matching."""
    return _normalize_plan_agents(
        agents,
        is_process_running=is_process_running,
    )


def load_live_plan_agents() -> list[Agent]:
    """Load just the agent rows needed to match pending PlanApproval notifications."""

    agents: list[Agent] = []
    project_files = get_all_project_files()
    agents.extend(load_agents_from_running_field(project_files, {}, {}))
    artifact_snapshot = artifact_snapshot_for_live_plan_load()
    agents.extend(load_plan_agents_from_artifact_snapshot(artifact_snapshot))
    return _normalize_live_plan_agents(agents)


def load_live_plan_agents_for_timestamps(timestamps: Iterable[str]) -> list[Agent]:
    """Load plan-matching agent rows from exact artifact timestamps."""

    normalized = normalize_timestamps(timestamps)
    if not normalized:
        return []

    agents = [
        agent
        for agent in load_agents_from_running_field(get_all_project_files(), {}, {})
        if agent.raw_suffix and normalize_to_14_digit(agent.raw_suffix) in normalized
    ]

    artifact_dirs = artifact_dirs_for_normalized_timestamps(normalized)
    if not artifact_dirs:
        return _normalize_live_plan_agents(agents)
    snapshot = scan_artifact_dirs_for_loader(
        artifact_dirs,
        PLAN_LIVE_SCAN_OPTIONS,
    )
    agents.extend(load_plan_agents_from_artifact_snapshot(snapshot))
    return _normalize_live_plan_agents(agents)


def load_all_agents(
    *,
    patch_snapshot: list[Patch] | None = None,
    artifact_snapshot: AgentArtifactScanWire | None = None,
) -> list[Agent]:
    """Load all running agents from all sources.

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. HOOKS field with suffix_type="running_agent" (fix_hook, summarize_hook)
    3. MENTORS field with suffix_type="running_agent"
    4. COMMENTS field with suffix_type="running_agent" (CRS)
    5. done.json marker files (DONE agents)

    Args:
        patch_snapshot: Optional pre-fetched Patch list. When
            supplied, the loader skips its own ``find_all_patches()``
            call and reuses this snapshot.

    Returns:
        List of Agent objects sorted by start time (most recent first),
        with agents that have no start time at the end.
    """
    agents, workflow_agent_steps = load_agents_from_all_sources(
        patch_snapshot=patch_snapshot,
        artifact_snapshot=artifact_snapshot,
    )
    return _normalize_loaded_agents(agents, workflow_agent_steps)


def load_tiered_agents(
    *,
    patch_snapshot: list[Patch] | None = None,
    full_history: bool = False,
    use_artifact_index: bool = True,
    index_freshness: Literal["revalidate", "cached"] = "cached",
    search_query: str | None = None,
    requested_limit: int | None = None,
    substages: dict[str, float] | None = None,
    allow_lock_busy_source_scan: bool = True,
) -> tuple[list[Agent], AgentLoadState]:
    """Load agents through the TUI tiered artifact path.

    When *substages* is given, it is updated with the always-on
    ``perf_counter`` timings for the ``index``, ``decode``, and
    ``provider`` (identity plus status normalization) loader substages.
    """

    from .agent_live_query_engine import agents_history_query_key
    from .agent_live_query_pushdown import compile_agents_live_query_pushdown

    live_query_plan = compile_agents_live_query_pushdown(search_query)
    raw_query = live_query_plan.raw_query
    window_safe = live_query_plan.window_safe
    candidate_filter = live_query_plan.candidate_filter
    history_query_key = agents_history_query_key(raw_query)
    pushdown_miss = bool(raw_query) and not window_safe
    defer_pushdown_miss = pushdown_miss and not full_history
    effective_full_history = full_history
    effective_limit = (
        requested_limit
        if requested_limit is not None
        and not effective_full_history
        and (window_safe or defer_pushdown_miss)
        else None
    )
    result = _load_agents_with_load_state(
        patch_snapshot=patch_snapshot,
        full_history=effective_full_history,
        use_artifact_index=use_artifact_index,
        index_freshness=index_freshness,
        requested_limit=effective_limit,
        candidate_filter=(
            candidate_filter
            if window_safe and (effective_limit is not None or effective_full_history)
            else None
        ),
        allow_lock_busy_source_scan=allow_lock_busy_source_scan,
    )
    provider_start = time.perf_counter()
    agents = _normalize_loaded_agents(result.agents, result.workflow_agent_steps)
    provider_elapsed = time.perf_counter() - provider_start
    if substages is not None:
        substages.update(result.substages)
        substages["provider"] = provider_elapsed
    state = replace(result.state, history_query_key=history_query_key)
    # A pushdown-miss query evaluated only against recent history is
    # query-incomplete. A non-truncated baseline read saw the whole visible
    # inbox, so it is not query-incomplete; only viewport-bounded reads and
    # truncated baseline reads are.
    if (
        defer_pushdown_miss
        and not state.complete_history
        and (state.bounded_prefix or state.truncated)
    ):
        state = replace(state, query_incomplete=True)
    if effective_limit is not None and result.state.bounded_prefix:
        if raw_query:
            agents, filtered_count = _filter_and_cap_windowed_agents_live(
                agents,
                raw_query,
                effective_limit,
            )
        else:
            filtered_count = len(agents)
            agents = agents[: max(1, effective_limit)]
        # The viewport cap slices the decoded roster after claim rows were
        # merged in, so claim rows could have been cut. Leave the load
        # non-authoritative for claims rather than carrying live claim rows
        # past the cap (keeps the merge contract explicit and bounded).
        state = replace(
            state,
            returned_count=len(agents),
            has_more=state.has_more or filtered_count > len(agents),
            running_claims_scanned=False,
        )
        return agents, state
    return agents, state


def _filter_and_cap_windowed_agents_live(
    agents: list[Agent],
    raw_query: str,
    requested_limit: int,
) -> tuple[list[Agent], int]:
    """Apply exact ``agents-live`` query semantics and cap a bounded prefix."""
    from sase.project_display_names import (
        attach_project_display_names,
        refresh_project_display_snapshot,
    )

    refresh_project_display_snapshot()
    attach_project_display_names(agents)
    from .agent_live_query_engine import apply_agents_live_query_filter

    filtered, _facade, error = apply_agents_live_query_filter(raw_query, agents)
    if error is not None:
        filtered = list(agents)
    return filtered[: max(1, requested_limit)], len(filtered)


def load_artifact_delta_agents(
    artifact_dirs: Sequence[Path | str],
    *,
    patch_snapshot: list[Patch] | None = None,
    changespec_snapshot: list[Patch] | None = None,  # legacy compatibility alias
    update_index: bool = True,
    deleted_artifact_dirs: Sequence[Path | str] = (),
) -> tuple[list[Agent], AgentLoadState]:
    """Load normalized agents from an exact set of artifact directories."""
    if patch_snapshot is None:
        patch_snapshot = changespec_snapshot  # legacy compatibility alias

    unique_dirs, seen_dirs, deleted_dir_keys = prepare_artifact_delta_paths(
        artifact_dirs,
        deleted_artifact_dirs,
    )

    snapshot = scan_artifact_dirs_for_loader(unique_dirs)
    update_artifact_index_from_delta(snapshot, update_index=update_index)
    state = artifact_delta_load_state(
        snapshot,
        seen_dirs=seen_dirs,
        deleted_dir_keys=deleted_dir_keys,
    )
    agents, workflow_agent_steps = load_agents_from_artifact_snapshot_sources(
        snapshot,
        patch_snapshot=patch_snapshot,
    )
    normalized = _normalize_loaded_agents(
        agents,
        workflow_agent_steps,
        keep_orphaned_followups=True,
    )
    _mark_live_artifact_delta_runners(normalized)
    return normalized, state

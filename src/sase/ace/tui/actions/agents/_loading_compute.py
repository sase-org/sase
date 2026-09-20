"""Pure-data compute helpers for :class:`AgentLoadingMixin`.

These helpers are safe to call from a worker thread — they do not touch
widgets, do not read app state, and (apart from the self-healing
artifact cleanup) do not write to disk. The mixin in :mod:`._loading`
folds their output back into ``self`` on the UI thread.

The implementation is split across three sibling modules:

* :mod:`._loading_compute_types` — pure-data dataclass types
* :mod:`._loading_compute_merge` — Tier 1 patch-merge over complete history
* :mod:`._loading_compute_finalize` — query/override/selection plan
* :mod:`._loading_graph` — worker-owned copies of cached UI row graphs

This module remains the public import facade so existing callers can
keep importing ``PreparedApplyData``, ``compute_apply_loaded_agents``,
etc. from ``_loading_compute``. Module-private compute pieces stay in
their sibling modules and are imported there directly (tests in
particular reach into the sibling modules for ``_compute_finalize_plan``
and friends).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.project_display_names import attach_project_display_names

from ._loading_compute_finalize import (
    attach_finalize_plan_to_boundary,
    make_finalize_stale_token,
)
from ._loading_compute_merge import merge_incomplete_load_after_complete_history
from ._loading_compute_types import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    PreparedFinalizePlan,
)
from ._loading_graph import adopt_prepared_apply_data, own_prepared_apply_snapshot
from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    is_always_visible,
    is_axe_spawned_agent,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.fold_state import FoldLevel

log = logging.getLogger(__name__)

__all__ = [
    "PreparedApplyBoundary",
    "PreparedApplyData",
    "PreparedApplySelectionInputs",
    "PreparedApplySnapshot",
    "PreparedFinalizePlan",
    "_CLEANED_ARTIFACT_DIRS",
    "_filter_agents_by_fold_snapshot",
    "attach_finalize_plan_to_boundary",
    "compute_apply_loaded_agents",
    "compute_loader_cleanup",
    "make_finalize_stale_token",
    "merge_incomplete_load_after_complete_history",
    "own_prepared_apply_snapshot",
    "prepare_loaded_agents_apply_boundary",
    "prepare_loaded_agents_worker_boundary",
    "project_and_fold_rosters",
    "rebase_prepared_apply_boundary_on_proc_projection",
]

# Per-process cache of artifact dirs already reconciled by the loader's
# self-healing pass.  First call inspects the dir (and may call
# ``delete_agent_artifacts``); subsequent full reloads skip it, saving the
# stat/glob syscalls when many dismissed agents accumulate.
_CLEANED_ARTIFACT_DIRS: set[str] = set()
_LOADER_CLEANUP_CONTENTION_TIMEOUT_SECONDS = 0.25


@dataclass(frozen=True)
class PreparedFoldFiltering:
    """Fold-filter output plus the unfiltered payload the UI must preserve.

    ``unfiltered_agents`` / ``visible_agents`` are the rosters the UI thread
    publishes: the local rows widened by the fleet projection, then fold
    filtered (see :func:`project_and_fold_rosters`). ``local_unfiltered_agents``
    is the roster before that projection and ``local_visible_agents`` the
    published rows that are not fleet rows; the UI thread needs them for its
    ``_agents_local_*`` mirrors, runner capacity, and content-search index.
    """

    unfiltered_agents: list[Agent]
    visible_agents: list[Agent]
    fold_counts: dict[str, tuple[int, int]]
    local_unfiltered_agents: list[Agent]
    local_visible_agents: list[Agent]


def project_and_fold_rosters(
    local_unfiltered: list[Agent],
    fleet_rows: Sequence[Agent],
    fold_levels: dict[str, FoldLevel] | None,
) -> tuple[list[Agent], list[Agent], dict[str, tuple[int, int]]]:
    """Return the published ``(unfiltered, visible, fold_counts)`` rosters.

    Projects *fleet_rows* into the local roster and only then fold filters the
    result, which is how fleet refresh reprojection and the query refilter
    derive it. The order matters: the clan-tree projection rebuilds a clan
    container only from the member rows it still sees, so projecting a roster
    that was already fold filtered silently drops the container of every
    collapsed clan (and with it a tribe panel made of clan containers).

    Pure and worker-safe. The dispatch-provisional reconciliation that produced
    *fleet_rows* is not: callers capture that result on the UI thread.
    """
    from ...models._agent_tree import project_mixed_agent_tree
    from ...util.trace import tui_trace

    unfiltered = project_mixed_agent_tree(local_unfiltered, list(fleet_rows))
    if fold_levels is None:
        return unfiltered, list(unfiltered), {}
    with tui_trace("agents.fold_filtering", count=len(unfiltered)):
        visible, fold_counts = _filter_agents_by_fold_snapshot(unfiltered, fold_levels)
    return unfiltered, visible, fold_counts


def _local_rows(agents: list[Agent]) -> list[Agent]:
    """Return the rows of *agents* that are not fleet rows."""
    return [agent for agent in agents if not agent.fleet_origin_alias]


def compute_loader_cleanup(
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    dismissed_from_loader: list[Agent],
) -> tuple[
    set[tuple[AgentType, str, str | None]],
    set[str],
]:
    """Compute orphaned-dismissed entries and clean loader-sourced artifacts."""
    from ._killing import delete_agent_artifacts

    del dismissed_snapshot
    orphaned: set[tuple[AgentType, str, str | None]] = set()

    # Self-healing: clean stale artifacts only for loader-sourced dismissed agents.
    cleaned_dirs: set[str] = set()
    for a in dismissed_from_loader:
        if a._loaded_from_dismissed_bundle:
            continue
        artifacts_dir = a.artifacts_dir or a.get_artifacts_dir()
        if artifacts_dir is None or artifacts_dir in _CLEANED_ARTIFACT_DIRS:
            continue
        if not Path(artifacts_dir).is_dir():
            cleaned_dirs.add(artifacts_dir)
            continue
        try:
            completed = delete_agent_artifacts(
                artifacts_dir,
                artifact_index_timeout_seconds=(
                    _LOADER_CLEANUP_CONTENTION_TIMEOUT_SECONDS
                ),
            )
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "busy" not in message and "locked" not in message:
                raise
            log.debug(
                "loader cleanup deferred for busy database: %s",
                artifacts_dir,
            )
            continue
        if completed is False:
            log.debug(
                "loader cleanup deferred for index contention: %s",
                artifacts_dir,
            )
            continue
        cleaned_dirs.add(artifacts_dir)

    return orphaned, cleaned_dirs


class _FoldStateSnapshot:
    """Read-only fold-state adapter for pure fold filtering."""

    def __init__(self, levels: dict[str, FoldLevel]) -> None:
        self._levels = levels

    def get(self, key: str) -> FoldLevel:
        from ...models.fold_state import FoldLevel

        return self._levels.get(key, FoldLevel.COLLAPSED)


def _filter_agents_by_fold_snapshot(
    agents: list[Agent],
    fold_levels: dict[str, FoldLevel],
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Fold-filter agents from an explicit fold-state snapshot."""
    from ...models._fold_filter import filter_agents_by_fold_state

    return filter_agents_by_fold_state(
        agents, cast(Any, _FoldStateSnapshot(fold_levels))
    )


def _proc_shells_from_apply_snapshot(
    snapshot: PreparedApplySnapshot,
) -> list[Agent]:
    """Return proc-shell rows the prepared apply should publish.

    A captured projection is the source of truth, including an empty one.
    Snapshots that never saw an observer fall back to cached roster shells.
    """
    from ...models.agent_proc_shells import proc_shell_agents_from_observed

    if snapshot.proc_projection is None:
        return [
            agent
            for agent in snapshot.cached_agents_with_children
            if agent.is_proc_shell
        ]
    return proc_shell_agents_from_observed(
        snapshot.proc_projection.rows,
        dismissed_proc_ids=snapshot.dismissed_proc_shells,
    )


def rebase_prepared_apply_boundary_on_proc_projection(
    boundary: PreparedApplyBoundary,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyBoundary:
    """Replace proc-shell rows on a prepared boundary with *snapshot*'s projection."""
    from ...models.agent_proc_shells import merge_proc_shell_agents

    proc_shells = _proc_shells_from_apply_snapshot(snapshot)
    prep = boundary.prep
    prep.filtered_agents = merge_proc_shell_agents(prep.filtered_agents, proc_shells)
    if prep.capacity_agents:
        prep.capacity_agents = merge_proc_shell_agents(
            prep.capacity_agents, proc_shells
        )
    if proc_shells:
        prep.has_always_visible = True
    local_unfiltered = merge_proc_shell_agents(
        boundary.fold.local_unfiltered_agents, proc_shells
    )
    unfiltered_agents, visible_agents, fold_counts = project_and_fold_rosters(
        local_unfiltered,
        snapshot.fleet_rows,
        snapshot.fold_levels,
    )
    return replace(
        boundary,
        fold=PreparedFoldFiltering(
            unfiltered_agents=unfiltered_agents,
            visible_agents=visible_agents,
            fold_counts=fold_counts,
            local_unfiltered_agents=local_unfiltered,
            local_visible_agents=_local_rows(visible_agents),
        ),
        proc_generation=snapshot.proc_generation,
        finalize=None,
        fleet_source_rows=snapshot.fleet_rows,
    )


def prepare_loaded_agents_apply_boundary(
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
    *,
    merge_incomplete: bool = True,
    effective_runner_limit: float | None = None,
    graphs_owned: bool = False,
) -> PreparedApplyBoundary:
    """Prepare pure post-load apply data from an explicit app-state snapshot.

    Cached UI rows are detached here unless the caller already took ownership
    (``graphs_owned=True``), so slot annotation and proc-shell carryover cannot
    mutate the displayed graph.
    """
    from ...util.trace import tui_trace

    fleet_source_rows = snapshot.fleet_rows
    if not graphs_owned:
        snapshot, memo = own_prepared_apply_snapshot(snapshot)
        prep = adopt_prepared_apply_data(prep, memo)
        graphs_owned = True

    if merge_incomplete:
        with tui_trace(
            "agents.incomplete_load_merge",
            incoming=len(prep.filtered_agents),
            cached=len(snapshot.cached_agents_with_children),
            complete=getattr(snapshot.load_state, "complete_history", None),
        ):
            prep = merge_incomplete_load_after_complete_history(
                prep,
                snapshot,
                graphs_owned=graphs_owned,
            )

    # The disk loader has no proc-shell source; stand-alone proc rows come
    # from the proc-observer projection captured on the snapshot. Merge that
    # projection (not only cached roster shells) before slot, fold, and
    # selection work so a projection-only shell is present at the first
    # finalize.
    from ...models.agent_proc_shells import merge_proc_shell_agents

    proc_shells = _proc_shells_from_apply_snapshot(snapshot)
    prep.filtered_agents = merge_proc_shell_agents(prep.filtered_agents, proc_shells)
    if proc_shells:
        # Proc-shell rows are never workflow children and never hidden, so the
        # hideable partition and hidden count remain correct as captured from
        # the loader payload; only the visible-presence flag needs widening.
        prep.has_always_visible = True

    # Derive slot counts/queue positions from the already-loaded, post-merge
    # refresh payload. This stays off the Textual event loop on async loads and
    # avoids a second artifact scan for display-only data.
    from sase.core.agent_hold_facade import active_agent_hold_records

    from ...models.agent_runner_slots import refresh_runner_slot_context

    active_holds = (
        tuple(active_agent_hold_records()) if effective_runner_limit is not None else ()
    )
    runner_capacity = refresh_runner_slot_context(
        prep.filtered_agents,
        effective_limit=effective_runner_limit,
        capacity_agents=prep.capacity_agents or None,
        active_holds=active_holds,
    )

    # Slot annotation above stays local-only. The fleet rows are projected in
    # before folding so the finalize plan is computed over the roster the UI
    # thread publishes, and so that roster matches what reprojection derives.
    local_unfiltered = list(prep.filtered_agents)
    unfiltered_agents, visible_agents, fold_counts = project_and_fold_rosters(
        local_unfiltered,
        snapshot.fleet_rows,
        snapshot.fold_levels,
    )

    return PreparedApplyBoundary(
        prep=prep,
        fold=PreparedFoldFiltering(
            unfiltered_agents=unfiltered_agents,
            visible_agents=visible_agents,
            fold_counts=fold_counts,
            local_unfiltered_agents=local_unfiltered,
            local_visible_agents=_local_rows(visible_agents),
        ),
        selection=snapshot.selection,
        runner_capacity=runner_capacity,
        capacity_generation=snapshot.capacity_generation,
        proc_generation=snapshot.proc_generation,
        fleet_source_rows=fleet_source_rows,
    )


def compute_apply_loaded_agents(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    *,
    dismissed_bundle_snapshot: set[tuple[AgentType, str, str | None]] | None = None,
) -> PreparedApplyData:
    """Pure-data filter pipeline for ``_apply_loaded_agents``.

    Computes the recovered-bundle / auto-dismiss deltas, applies the
    dismissed-set filter, marks axe-spawned agents hidden, and partitions
    the result into always-visible vs hideable. Returns a
    :class:`_PreparedApplyData` snapshot for the UI thread to fold into
    ``self``. Safe to call from a worker thread — does not access widgets,
    does not write to disk, does not mutate ``self`` state.
    """
    recovered = {
        a.identity
        for a in dismissed_from_loader
        if a._loaded_from_dismissed_bundle and a.identity not in dismissed_snapshot
    }

    # The filter must treat bundle-index identities and freshly-recovered
    # identities as dismissed so source scans match index-backed loads and a
    # re-recovered agent doesn't briefly leak into the visible list before
    # the UI thread persists the recovery delta.
    effective_dismissed = (
        dismissed_snapshot | (dismissed_bundle_snapshot or set()) | recovered
    )
    dismissed_suffixes: set[str] = {
        raw_suffix for _, _, raw_suffix in effective_dismissed if raw_suffix is not None
    }
    dismissed_cl_suffixes: set[tuple[str, str]] = {
        (cl_name, raw_suffix)
        for _, cl_name, raw_suffix in effective_dismissed
        if raw_suffix is not None
    }

    # Filter out dismissed agents. Verified live-runner rows outrank stale
    # terminal dismissal identities: family normalization may have replaced
    # their RUNNING label with RETRYING or another semantic status.
    # Non-RUNNING agents use the broad dismissed_suffixes index (suffix-only).
    # RUNNING agents use the
    # narrower dismissed_cl_suffixes index (cl_name, raw_suffix) to
    # avoid cross-Patch contamination while still catching agents that
    # reappear with a different AgentType after dedup (e.g. a killed
    # WORKFLOW agent whose artifacts are deleted but whose RUNNING
    # field entry persists, producing an AgentType.RUNNING agent).
    # RUNNING agents with cl_name="unknown" fall back to suffix-only
    # matching since "unknown" is a transient placeholder from the
    # RUNNING field that gets resolved during dedup.
    filtered = [
        a
        for a in all_agents
        if (a.runner_is_live or a.identity not in effective_dismissed)
        and (
            a.runner_is_live
            or a.status == "RUNNING"
            or (a.raw_suffix is None or a.raw_suffix not in dismissed_suffixes)
        )
        and not (
            not a.runner_is_live
            and a.status == "RUNNING"
            and a.raw_suffix is not None
            and (
                (a.cl_name, a.raw_suffix) in dismissed_cl_suffixes
                or (a.cl_name == "unknown" and a.raw_suffix in dismissed_suffixes)
            )
        )
    ]

    # Auto-dismiss hidden agents that have completed successfully.
    # Failed agents are kept visible so the user can investigate.
    auto_dismissed_ids = {
        a.identity
        for a in filtered
        if a.hidden and a.status in DISMISSABLE_STATUSES and a.status != "FAILED"
    }
    if auto_dismissed_ids:
        filtered = [a for a in filtered if a.identity not in auto_dismissed_ids]

    # Mark axe-spawned agents as hidden so the icon renders correctly.
    for agent in filtered:
        if not agent.hidden and is_axe_spawned_agent(agent):
            agent.hidden = True

    capacity_agents = list(filtered)

    # Categorize agents: always-visible (dismissable OR running) vs hideable
    always_visible: list[Agent] = []
    hideable: list[Agent] = []
    for a in filtered:
        if is_always_visible(a):
            always_visible.append(a)
        else:
            hideable.append(a)

    has_always_visible = len(always_visible) > 0
    if has_always_visible and hide_non_run_agents and hideable:
        result_agents = always_visible
        hidden_count = len(hideable)
    else:
        result_agents = filtered
        hidden_count = 0

    from ...models._agent_tree import project_clan_tree

    result_agents = project_clan_tree(result_agents)
    attach_project_display_names([*result_agents, *dismissed_from_loader])

    return PreparedApplyData(
        filtered_agents=result_agents,
        has_always_visible=has_always_visible,
        hidden_count=hidden_count,
        hideable_agents=hideable,
        dismissed_agent_objects=dismissed_from_loader,
        capacity_agents=capacity_agents,
        recovered_bundle_identities=recovered,
        auto_dismissed_identities=auto_dismissed_ids,
    )


def _prepare_loaded_agents_worker_prep(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
    *,
    dismissed_bundle_snapshot: set[tuple[AgentType, str, str | None]] | None = None,
    graphs_owned: bool = False,
) -> PreparedApplyData:
    """Prepare async-loaded agents, including post-history Tier 1 patch merge."""
    from ...util.trace import tui_trace

    prep = compute_apply_loaded_agents(
        all_agents,
        dismissed_from_loader,
        dismissed_snapshot,
        hide_non_run_agents,
        dismissed_bundle_snapshot=dismissed_bundle_snapshot,
    )
    snapshot_for_merge = replace(
        snapshot,
        dismissed_agents=(
            set(snapshot.dismissed_agents)
            | (dismissed_bundle_snapshot or set())
            | prep.recovered_bundle_identities
            | prep.auto_dismissed_identities
        ),
    )
    with tui_trace(
        "agents.incomplete_load_merge",
        incoming=len(prep.filtered_agents),
        cached=len(snapshot.cached_agents_with_children),
        complete=getattr(snapshot.load_state, "complete_history", None),
    ):
        return merge_incomplete_load_after_complete_history(
            prep,
            snapshot_for_merge,
            graphs_owned=graphs_owned,
        )


def prepare_loaded_agents_worker_boundary(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
    *,
    dismissed_bundle_snapshot: set[tuple[AgentType, str, str | None]] | None = None,
) -> PreparedApplyBoundary:
    """Prepare async-loaded agents through the fold-filter boundary.

    Detaches the captured UI graph once on this worker, then keeps that
    ownership through merge, proc-shell carryover, and slot annotation.
    """
    from sase.config.core import get_max_running_agents

    from ...models._agent_graph import adopt_agents

    fleet_source_rows = snapshot.fleet_rows
    snapshot, memo = own_prepared_apply_snapshot(snapshot)
    all_agents = adopt_agents(all_agents, memo)
    dismissed_from_loader = adopt_agents(dismissed_from_loader, memo)
    prep = _prepare_loaded_agents_worker_prep(
        all_agents,
        dismissed_from_loader,
        dismissed_snapshot,
        hide_non_run_agents,
        snapshot,
        dismissed_bundle_snapshot=dismissed_bundle_snapshot,
        graphs_owned=True,
    )
    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        snapshot,
        merge_incomplete=False,
        effective_runner_limit=get_max_running_agents(),
        graphs_owned=True,
    )
    return replace(boundary, fleet_source_rows=fleet_source_rows)

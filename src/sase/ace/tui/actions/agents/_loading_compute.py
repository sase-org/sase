"""Pure-data compute helpers for :class:`AgentLoadingMixin`.

These helpers are safe to call from a worker thread — they do not touch
widgets, do not read app state, and (apart from the self-healing
artifact cleanup) do not write to disk. The mixin in :mod:`._loading`
folds their output back into ``self`` on the UI thread.

The implementation is split across three sibling modules:

* :mod:`._loading_compute_types` — pure-data dataclass types
* :mod:`._loading_compute_merge` — Tier 1 patch-merge over complete history
* :mod:`._loading_compute_finalize` — query/override/selection plan

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
from dataclasses import dataclass
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
    "prepare_loaded_agents_apply_boundary",
    "prepare_loaded_agents_worker_boundary",
]

# Per-process cache of artifact dirs already reconciled by the loader's
# self-healing pass.  First call inspects the dir (and may call
# ``delete_agent_artifacts``); subsequent full reloads skip it, saving the
# stat/glob syscalls when many dismissed agents accumulate.
_CLEANED_ARTIFACT_DIRS: set[str] = set()
_LOADER_CLEANUP_CONTENTION_TIMEOUT_SECONDS = 0.25


@dataclass(frozen=True)
class PreparedFoldFiltering:
    """Fold-filter output plus the unfiltered payload the UI must preserve."""

    unfiltered_agents: list[Agent]
    visible_agents: list[Agent]
    fold_counts: dict[str, tuple[int, int]]


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


def prepare_loaded_agents_apply_boundary(
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
    *,
    merge_incomplete: bool = True,
    configured_runner_limit: int | None = None,
) -> PreparedApplyBoundary:
    """Prepare pure post-load apply data from an explicit app-state snapshot."""
    from ...util.trace import tui_trace

    if merge_incomplete:
        with tui_trace(
            "agents.incomplete_load_merge",
            incoming=len(prep.filtered_agents),
            cached=len(snapshot.cached_agents_with_children),
            complete=getattr(snapshot.load_state, "complete_history", None),
        ):
            prep = merge_incomplete_load_after_complete_history(prep, snapshot)

    # Derive slot counts/queue positions from the already-loaded, post-merge
    # refresh payload. This stays off the Textual event loop on async loads and
    # avoids a second artifact scan for display-only data.
    from ...models.agent_runner_slots import refresh_runner_slot_context

    runner_capacity = refresh_runner_slot_context(
        prep.filtered_agents,
        configured_limit=configured_runner_limit,
    )

    unfiltered_agents = list(prep.filtered_agents)
    if snapshot.fold_levels is None:
        visible_agents = list(unfiltered_agents)
        fold_counts: dict[str, tuple[int, int]] = {}
    else:
        with tui_trace("agents.fold_filtering", count=len(unfiltered_agents)):
            visible_agents, fold_counts = _filter_agents_by_fold_snapshot(
                unfiltered_agents, snapshot.fold_levels
            )

    return PreparedApplyBoundary(
        prep=prep,
        fold=PreparedFoldFiltering(
            unfiltered_agents=unfiltered_agents,
            visible_agents=visible_agents,
            fold_counts=fold_counts,
        ),
        selection=snapshot.selection,
        runner_capacity=runner_capacity,
    )


def compute_apply_loaded_agents(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
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

    # The filter must treat freshly-recovered identities as dismissed so a
    # re-recovered agent doesn't briefly leak into the visible list before
    # the UI thread persists the recovery delta.
    effective_dismissed = dismissed_snapshot | recovered
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
    # avoid cross-ChangeSpec contamination while still catching agents that
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
        recovered_bundle_identities=recovered,
        auto_dismissed_identities=auto_dismissed_ids,
    )


def _prepare_loaded_agents_worker_prep(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyData:
    """Prepare async-loaded agents, including post-history Tier 1 patch merge."""
    from ...util.trace import tui_trace

    prep = compute_apply_loaded_agents(
        all_agents,
        dismissed_from_loader,
        dismissed_snapshot,
        hide_non_run_agents,
    )
    snapshot_for_merge = PreparedApplySnapshot(
        cached_agents_with_children=snapshot.cached_agents_with_children,
        dismissed_agents=(
            set(snapshot.dismissed_agents)
            | prep.recovered_bundle_identities
            | prep.auto_dismissed_identities
        ),
        agents_seen_complete_history=snapshot.agents_seen_complete_history,
        hide_non_run_agents=snapshot.hide_non_run_agents,
        load_state=snapshot.load_state,
        fold_levels=snapshot.fold_levels,
        selection=snapshot.selection,
        agent_panels_grouped=snapshot.agent_panels_grouped,
    )
    with tui_trace(
        "agents.incomplete_load_merge",
        incoming=len(prep.filtered_agents),
        cached=len(snapshot.cached_agents_with_children),
        complete=getattr(snapshot.load_state, "complete_history", None),
    ):
        return merge_incomplete_load_after_complete_history(prep, snapshot_for_merge)


def prepare_loaded_agents_worker_boundary(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyBoundary:
    """Prepare async-loaded agents through the fold-filter boundary."""
    from sase.config.core import get_max_running_agents

    prep = _prepare_loaded_agents_worker_prep(
        all_agents,
        dismissed_from_loader,
        dismissed_snapshot,
        hide_non_run_agents,
        snapshot,
    )
    return prepare_loaded_agents_apply_boundary(
        prep,
        snapshot,
        merge_incomplete=False,
        configured_runner_limit=get_max_running_agents(),
    )

"""Delta-scaled preparation for exact-artifact deltas.

Small ``artifact_delta`` loads currently pay full-corpus preparation when
the roster has ordinary sessions, clans, capacity, or a live capacity
report. This module uses the bounded affected-graph ownership primitive
to copy only the write set, then runs status, slot, and clan projections
on those detached rows while live unaffected rows stay read-only.

The scoped path only triggers for scalar-only deltas: every incoming row
matches a cached row by identity, the affected closure is eligible, no
new roots, no deletions, no dismissals, no repair, no bounded prefix, no
running-claims scans. Membership, order, dedup, identity, query, and
oversized-closure cases fall back to the full pipeline.

For eligible scalar deltas the global order, dedup, and reattach passes
are no-ops (their keys are all in the relationship set), so the scoped
path:

* owns only the affected closure via ``own_affected_apply_snapshot``,
* patches incoming scalars onto those detached rows,
* runs scoped status normalization on the closure,
* scopes tree projection to affected clans,
* builds capacity snapshots via O(N) reads and applies slot writes to
  detached rows, copy-on-write when an unrelated waiter/runner actually
  changes,
* runs fold filtering as a read-only selection,
* shares back only the closure (unaffected rows are already live).

Fallback preserves exactness: any uncertainty returns None and the caller
runs the full pipeline unchanged.
"""

from __future__ import annotations

from copy import copy
from dataclasses import fields
from typing import TYPE_CHECKING

from ...models._agent_graph import AGENT_RELINK_FIELDS, AffectedClosure
from ...models.agent import Agent
from ._loading_compute_merge import merge_clan_context

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

    from ...models.agent import AgentType
    from ...models.agent_runner_slots import RunnerCapacitySnapshot
    from ._loading_compute_types import PreparedApplySnapshot

_SCALAR_ONLY_MAX_INCOMING = 16
_SCALAR_ONLY_MIN_CACHED = 100
_SLOT_STATUSES = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "WAITING",
        "Queued",
        "Running",
        "Waiting",
    }
)


def _apply_incoming_scalars(owned: Agent, incoming: Agent) -> None:
    """Copy scalar fields from worker-owned *incoming* onto a detached row."""
    owned.clan_context = merge_clan_context(owned.clan_context, incoming.clan_context)
    skip = set(AGENT_RELINK_FIELDS)
    skip.add("clan_context")
    for field in fields(Agent):
        if field.name in skip:
            continue
        value = getattr(incoming, field.name)
        if isinstance(value, (list, dict, set)):
            value = copy(value)
        setattr(owned, field.name, value)


def _normalize_owned_closure(roster: list[Agent], closure: AffectedClosure) -> None:
    """Rebuild session presentation only on detached affected rows."""
    from ...models._agent_status_apply import apply_status_overrides

    owned = [agent for agent in roster if agent.identity in closure.affected_identities]
    if not owned:
        return
    top_level = [agent for agent in owned if not agent.parent_workflow]
    workflow_steps = [agent for agent in owned if agent.parent_workflow]
    apply_status_overrides(
        top_level,
        workflow_steps,
        classify_diff_badges=False,
    )


def _project_affected_clans(
    roster: list[Agent],
    closure: AffectedClosure,
) -> list[Agent]:
    """Project clan trees only for clans that intersect the write set."""
    from ...models._agent_tree import project_clan_tree

    by_identity = {agent.identity: agent for agent in roster}
    affected_clan_keys: set[tuple[str | None, str | None]] = set()
    for ident in closure.affected_identities:
        agent = by_identity.get(ident)
        if agent is None or not agent.agent_clan:
            continue
        affected_clan_keys.add((agent.agent_clan, agent.agent_clan_generation))
    if not affected_clan_keys:
        return roster

    def _in_affected_clan(agent: Agent) -> bool:
        return (agent.agent_clan, agent.agent_clan_generation) in affected_clan_keys

    first_idx = next(
        (index for index, agent in enumerate(roster) if _in_affected_clan(agent)),
        None,
    )
    if first_idx is None:
        return roster
    clan_rows = [agent for agent in roster if _in_affected_clan(agent)]
    projected = project_clan_tree(clan_rows)
    kept_before = [
        agent for agent in roster[:first_idx] if not _in_affected_clan(agent)
    ]
    kept_after = [agent for agent in roster[first_idx:] if not _in_affected_clan(agent)]
    return [*kept_before, *projected, *kept_after]


def _slot_signature(agent: Agent) -> tuple[object, ...]:
    return (
        agent.status,
        agent.runner_slots_in_use,
        agent.runner_slot_queue_position,
        agent.runner_slot_queue_size,
        agent.runner_occupied_capacity,
        agent.runner_effective_limit,
        agent.runner_admission_limit,
        agent.runner_capacity_blockers,
    )


def _slot_write_candidate(agent: Agent) -> bool:
    if agent.slot_requested_at or agent.runner_is_live or agent.is_clan_container:
        return True
    return agent.status in _SLOT_STATUSES


def _delta_changes_capacity(
    roster: list[Agent],
    incoming: list[Agent],
) -> bool:
    from sase.agent.status_buckets import agent_status_bucket

    by_identity = {agent.identity: agent for agent in roster}
    for inc in incoming:
        live = by_identity.get(inc.identity)
        if live is None:
            return True
        if bool(live.runner_is_live) != bool(inc.runner_is_live):
            return True
        if live.pid != inc.pid or live.slot_requested_at != inc.slot_requested_at:
            return True
        try:
            if agent_status_bucket(live) != agent_status_bucket(inc):
                return True
        except Exception:
            if live.status != inc.status:
                return True
    return False


def _apply_scoped_slot_context(
    roster: list[Agent],
    closure: AffectedClosure,
    snapshot: PreparedApplySnapshot,
    memo: dict[int, Agent],
    *,
    occupancy_changed: bool,
) -> tuple[RunnerCapacitySnapshot, list[Agent]]:
    """Apply slot writes to detached rows; copy-on-write changed waiters."""
    from sase.config.core import get_max_running_agents
    from sase.core.agent_hold_facade import active_agent_hold_records

    from ...models._agent_graph import copy_agent_rows_delta_isolated
    from ...models.agent_runner_slots import refresh_runner_slot_context

    owned_rows = [
        agent for agent in roster if agent.identity in closure.affected_identities
    ]
    extras: list[Agent] = []
    if occupancy_changed:
        extras = [
            agent
            for agent in roster
            if agent.identity not in closure.affected_identities
            and _slot_write_candidate(agent)
        ]
    extra_copies = copy_agent_rows_delta_isolated(extras, memo) if extras else []
    original_signatures = {extra.identity: _slot_signature(extra) for extra in extras}
    write_targets = [*owned_rows, *extra_copies]
    report = snapshot.capacity_report
    try:
        active_holds = tuple(active_agent_hold_records())
    except Exception:
        active_holds = ()
    if report is None:
        runner_capacity = refresh_runner_slot_context(
            write_targets,
            effective_limit=float(get_max_running_agents()),
            capacity_agents=roster,
            active_holds=active_holds,
        )
    else:
        runner_capacity = refresh_runner_slot_context(
            write_targets,
            capacity_agents=roster,
            raw_snapshot=report.raw_snapshot,
            report=report,
        )
    replacements = {
        extra.identity: copy_row
        for extra, copy_row in zip(extras, extra_copies, strict=True)
        if _slot_signature(copy_row) != original_signatures[extra.identity]
    }
    if replacements:
        roster = [replacements.get(agent.identity, agent) for agent in roster]
    return runner_capacity, roster


def _fold_filter(
    agents: list[Agent],
    snapshot: PreparedApplySnapshot,
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    if snapshot.fold_levels is None:
        return list(agents), {}
    from ...models.fold_state import FoldLevel
    from ...models._fold_filter import filter_agents_by_fold_state

    class _FoldStateSnapshot:
        def __init__(self, levels: dict[str, FoldLevel]) -> None:
            self._levels = levels

        def get(self, key: str) -> FoldLevel:
            return self._levels.get(key, FoldLevel.COLLAPSED)

    return filter_agents_by_fold_state(
        agents,
        _FoldStateSnapshot(snapshot.fold_levels),  # type: ignore[arg-type]
    )


def try_scoped_worker_boundary(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
    *,
    dismissed_bundle_snapshot: AbstractSet[tuple[AgentType, str, str | None]]
    | None = None,
) -> object | None:
    """Attempt the delta-scaled worker boundary for mixed-roster scalars.

    Returns a ``PreparedApplyBoundary`` equivalent to the full pipeline for
    bounded scalar exact deltas, including ordinary sessions, clans, and a
    live capacity report. A non-None capacity report or an unrelated
    session elsewhere in the roster does not by itself force fallback.
    Membership, repair, query, removal, and oversized closures still use
    the full path.
    """
    del dismissed_snapshot
    from ._loading_graph import (
        classify_exact_delta_fast_path,
        own_affected_apply_snapshot,
    )

    fleet_source_rows = snapshot.fleet_rows
    fast = classify_exact_delta_fast_path(snapshot)
    if not fast.eligible:
        return None
    if dismissed_from_loader:
        return None
    if dismissed_bundle_snapshot:
        try:
            if len(dismissed_bundle_snapshot) > 0:  # type: ignore[arg-type]
                return None
        except Exception:
            return None
    if snapshot.explicit_removals is not None:
        from ._removal_tombstones import EMPTY_EXPLICIT_REMOVALS

        if snapshot.explicit_removals is not EMPTY_EXPLICIT_REMOVALS:
            try:
                if len(snapshot.explicit_removals) > 0:  # type: ignore[arg-type]
                    return None
            except Exception:
                return None
    load_state = snapshot.load_state
    deleted_dirs = set(
        getattr(load_state, "deleted_artifact_dirs", frozenset()) or frozenset()
        if load_state is not None
        else frozenset()
    )
    if deleted_dirs:
        return None

    incoming = list(all_agents)
    cached = list(snapshot.cached_agents_with_children)
    if not incoming or not cached:
        return None
    if len(incoming) > _SCALAR_ONLY_MAX_INCOMING:
        return None
    if len(cached) < _SCALAR_ONLY_MIN_CACHED:
        return None

    occupancy_changed = _delta_changes_capacity(cached, incoming)
    owned = own_affected_apply_snapshot(snapshot, incoming)
    if owned is None:
        return None
    snapshot, memo, closure = owned
    roster = list(snapshot.cached_agents_with_children)
    by_identity = {agent.identity: agent for agent in roster}
    for inc in incoming:
        owned_row = by_identity.get(inc.identity)
        if owned_row is None:
            return None
        _apply_incoming_scalars(owned_row, inc)

    _normalize_owned_closure(roster, closure)
    roster = _project_affected_clans(roster, closure)
    runner_capacity, roster = _apply_scoped_slot_context(
        roster,
        closure,
        snapshot,
        memo,
        occupancy_changed=occupancy_changed,
    )

    if snapshot.proc_projection is not None:
        from ...models.agent_named_procs import (
            merge_named_proc_agents,
            named_proc_agents_from_observed,
        )

        named_procs = named_proc_agents_from_observed(
            snapshot.proc_projection.rows,
            dismissed_proc_ids=snapshot.dismissed_named_procs,
        )
        roster = merge_named_proc_agents(roster, named_procs)

    from sase.project_display_names import attach_project_display_names

    attach_project_display_names(
        [agent for agent in roster if agent.identity in closure.affected_identities]
    )

    from ._loading_helpers import is_always_visible

    always_visible = [agent for agent in roster if is_always_visible(agent)]
    hideable = [agent for agent in roster if not is_always_visible(agent)]
    if always_visible and bool(hide_non_run_agents) and hideable:
        filtered = always_visible
        hidden_count = len(hideable)
    else:
        filtered = list(roster)
        hidden_count = 0

    from ._loading_compute_types import PreparedApplyData

    capacity_agents = list(snapshot.capacity_agents_with_children) or list(filtered)
    prep = PreparedApplyData(
        filtered_agents=filtered,
        has_always_visible=bool(always_visible),
        hidden_count=hidden_count,
        hideable_agents=hideable,
        dismissed_agent_objects=[],
        capacity_agents=capacity_agents,
    )

    visible, fold_counts = _fold_filter(filtered, snapshot)

    def _local_rows(rows: list[Agent]) -> list[Agent]:
        return [agent for agent in rows if not agent.fleet_origin_alias]

    from ._loading_compute import PreparedFoldFiltering
    from ._loading_compute_types import PreparedApplyBoundary

    copied = sum(
        1
        for live_row, owned_row in zip(
            cached, snapshot.cached_agents_with_children, strict=True
        )
        if live_row is not owned_row
    )
    from ...util.trace import tui_trace

    with tui_trace(
        "agents.delta_prep_scaled",
        incoming=len(incoming),
        cached=len(cached),
        closure=closure.closure_size,
        copied=copied,
        reason=closure.reason,
    ):
        pass

    return PreparedApplyBoundary(
        prep=prep,
        fold=PreparedFoldFiltering(
            unfiltered_agents=list(filtered),
            visible_agents=visible,
            fold_counts=fold_counts,
            local_unfiltered_agents=list(filtered),
            local_visible_agents=_local_rows(visible),
        ),
        selection=snapshot.selection,
        runner_capacity=runner_capacity,
        runner_capacity_estimate=runner_capacity,
        capacity_generation=snapshot.capacity_generation,
        proc_generation=snapshot.proc_generation,
        fleet_source_rows=tuple(fleet_source_rows),
        dismissed_agents_snapshot=frozenset(snapshot.dismissed_agents),
        removal_generation=snapshot.removal_generation,
    )

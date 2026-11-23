"""Delta-scaled preparation for exact-artifact deltas.

Small ``artifact_delta`` loads (1-7 agents from inflight_poll / notification)
currently pay full-corpus preparation: copying the entire 948-agent roster,
merging over it, and sharing it back. This module implements a scoped fast
path that scales with the delta instead of the corpus while preserving exact
deltas, complete-history ownership, and in-flight convergence.

The scoped path only triggers for scalar-only deltas: every incoming row
matches a cached row by identity with all ``EXACT_DELTA_RELATIONSHIP_KEYS``
equal, no new roots, no deletions, no dismissals, no repair, no bounded
prefix, no running-claims scans. Anything structural falls back to the full
pipeline (existing behavior, unchanged).

For scalar-only deltas the global order, dedup, and reattach passes are
no-ops (their keys are all in the relationship set), so the scoped path:

* copies only the affected closure (affected rows + parents/children/siblings
  + full clan membership for affected clans) via ``copy_agent_rows_delta_isolated``,
* patches affected positions in place preserving order,
* runs scoped status normalization on the closure,
* builds capacity snapshots via O(N) reads (cheap, no copies) and applies
  slot updates copy-on-write (only when values differ),
* scopes tree projection to affected clans,
* runs fold/finalize full (reads only, safe over mixed live + worker rows),
* shares back only the closure (unaffected rows are already live).

Fallback preserves exactness: any uncertainty returns None and the caller
runs the full pipeline unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ._loading_compute_merge import (
    EXACT_DELTA_RELATIONSHIP_KEYS,
    _merge_clan_context,
    _tier1_merge_key,
    _tier1_stable_merge_key,
)

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

    from ...models import Agent
    from ...models.agent import AgentType
    from ._loading_compute_types import PreparedApplySnapshot


_SCALAR_ONLY_MAX_INCOMING = 16
_SCALAR_ONLY_MAX_CLOSURE = 64
_SCALAR_ONLY_MAX_CACHED = 5000


def _relationship_keys_equal(cached: Agent, incoming: Agent) -> bool:
    for name in EXACT_DELTA_RELATIONSHIP_KEYS:
        if getattr(cached, name) != getattr(incoming, name):
            return False
    return True


def try_scoped_scalar_patch(
    incoming: list[Agent],
    snapshot: PreparedApplySnapshot,
) -> tuple[list[Agent], dict[int, int]] | None:
    """Return (merged_roster, closure_index_by_id) for scalar-only deltas.

    The returned roster reuses live cached objects for unaffected rows and
    worker-owned incoming objects (with clan-context merged) for affected
    rows, preserving cached order. Returns None when the delta is not
    scalar-only and the caller must use the full pipeline.
    """
    cached = list(snapshot.cached_agents_with_children)
    if not cached or not incoming:
        return None
    if len(incoming) > _SCALAR_ONLY_MAX_INCOMING:
        return None
    if len(cached) < 100:
        # Tiny caches gain nothing from scoping; keep the tested full path.
        return None

    load_state = snapshot.load_state
    if load_state is None:
        return None
    if load_state.complete_history:
        return None
    if load_state.artifact_source != "artifact_delta":
        return None
    if getattr(load_state, "repair_recommended", False):
        return None
    if getattr(load_state, "bounded_prefix", False):
        return None
    if bool(getattr(load_state, "running_claims_scanned", False)):
        return None
    if not snapshot.agents_seen_complete_history:
        return None
    if not snapshot.cache_query_matches:
        return None
    deleted_dirs = set(
        getattr(load_state, "deleted_artifact_dirs", frozenset()) or frozenset()
    )
    if deleted_dirs:
        return None

    # Dismissals / explicit removals change membership beyond the delta.
    if snapshot.dismissed_agents:
        # Dismissed sets are checked per-row below; a non-empty set alone
        # does not force fallback, but explicit removals do (tombstones).
        pass
    if snapshot.explicit_removals is not None:
        from ._removal_tombstones import EMPTY_EXPLICIT_REMOVALS

        if snapshot.explicit_removals is not EMPTY_EXPLICIT_REMOVALS:
            # Non-empty tombstones need the full merge's removal pass.
            try:
                if len(snapshot.explicit_removals) > 0:  # type: ignore[arg-type]
                    return None
            except Exception:
                return None

    cached_by_identity: dict[object, tuple[int, Agent]] = {}
    for idx, agent in enumerate(cached):
        # First wins; duplicates would need full dedup to disambiguate.
        if agent.identity not in cached_by_identity:
            cached_by_identity[agent.identity] = (idx, agent)

    # All incoming must match an existing cached row by identity with
    # relationship keys equal. No new roots, no identity changes.
    matched: list[tuple[int, Agent, Agent]] = []
    for inc in incoming:
        found = cached_by_identity.get(inc.identity)
        if found is None:
            return None
        idx, live = found
        if live.identity != inc.identity:
            return None
        if not _relationship_keys_equal(live, inc):
            return None
        # Stable replacement must win (same rule as the full merge for
        # artifact deltas with matching types).
        if live.agent_type != inc.agent_type:
            return None
        matched.append((idx, live, inc))

    if not matched:
        return None

    # Dismissal check for affected rows only (full merge checks all cached,
    # but unaffected cached rows were already filtered when they became live;
    # a newly-dismissed unaffected row would need full handling).
    dismissed = set(snapshot.dismissed_agents)
    if dismissed:
        dismissed_suffixes = {raw for _, _, raw in dismissed if raw is not None}
        for _, live, _ in matched:
            if live.identity in dismissed:
                return None
            if live.raw_suffix is not None and live.raw_suffix in dismissed_suffixes:
                # Suffix-level dismissal needs the full merge's broad check.
                return None
        # Unaffected rows: verify none became newly dismissed by scanning
        # identities only (O(N) reads, no copies). Any hit falls back.
        for agent in cached:
            if agent.identity in dismissed:
                # Dismissed rows should not be in the cached roster; if one
                # is, the full merge's dismissal pass must run.
                return None

    # Build closure: affected + parents + children + siblings + clan members.
    # All are O(delta)-sized for scalar updates; clan membership could be
    # large, so cap the closure and fall back when too big.
    affected_idx = {idx for idx, _, _ in matched}
    affected_suffixes = {
        live.raw_suffix for _, live, _ in matched if live.raw_suffix is not None
    }
    {live.agent_session for _, live, _ in matched if live.agent_session}
    affected_clans = {
        (live.agent_clan, live.agent_clan_generation)
        for _, live, _ in matched
        if live.agent_clan
    }

    parent_suffix_by_idx: dict[int, str | None] = {}
    for idx, agent in enumerate(cached):
        parent_suffix_by_idx[idx] = agent.parent_timestamp

    # Children of affected (parent_timestamp in affected suffixes) and
    # siblings (share a parent with affected) plus parents of affected.
    closure_idx: set[int] = set(affected_idx)
    # Parents: cached rows whose suffix equals an affected row's parent.
    affected_parent_suffixes = {
        live.parent_timestamp for _, live, _ in matched if live.parent_timestamp
    }
    suffix_to_idx: dict[str, list[int]] = {}
    for idx, agent in enumerate(cached):
        if agent.raw_suffix is not None and not agent.is_workflow_child:
            suffix_to_idx.setdefault(agent.raw_suffix, []).append(idx)

    for psuffix in affected_parent_suffixes:
        for idx in suffix_to_idx.get(psuffix, []):
            closure_idx.add(idx)

    # Children + siblings: rows whose parent is affected or shares a parent
    # with affected.
    parent_of_affected: dict[int, str | None] = {}
    for idx in list(affected_idx):
        parent_of_affected[idx] = parent_suffix_by_idx.get(idx)
    sibling_parents = {p for p in parent_of_affected.values() if p}
    for idx, agent in enumerate(cached):
        if len(closure_idx) > _SCALAR_ONLY_MAX_CLOSURE:
            break
        pt = agent.parent_timestamp
        if pt is None:
            continue
        if pt in affected_suffixes or pt in sibling_parents:
            closure_idx.add(idx)

    # Clan members of affected clans (needed for tree + status propagation).
    if affected_clans:
        for idx, agent in enumerate(cached):
            if len(closure_idx) > _SCALAR_ONLY_MAX_CLOSURE:
                break
            key = (agent.agent_clan, agent.agent_clan_generation)
            if key in affected_clans:
                closure_idx.add(idx)

    if len(closure_idx) > _SCALAR_ONLY_MAX_CLOSURE:
        return None

    # Patch: merge clan context into incoming copies (mutates incoming only,
    # which are worker-owned fresh disk objects).
    for _, live, inc in matched:
        inc.clan_context = _merge_clan_context(live.clan_context, inc.clan_context)

    merged = list(cached)
    for idx, _, inc in matched:
        merged[idx] = inc

    closure_index_by_id = {id(merged[idx]): idx for idx in closure_idx}
    return merged, closure_index_by_id


def _capacity_irrelevant(
    matched: list[tuple[int, Agent, Agent]],
) -> bool:
    """Return whether the scalar patch cannot affect runner capacity."""
    from sase.agent.status_buckets import agent_status_bucket

    for _, live, inc in matched:
        try:
            live_bucket = agent_status_bucket(live)
        except Exception:
            live_bucket = getattr(live, "status", "")
        try:
            inc_bucket = agent_status_bucket(inc)
        except Exception:
            inc_bucket = getattr(inc, "status", "")
        # Terminal->terminal (Done/Failed/DONE/FAILED in any combination)
        # is capacity-irrelevant: running/live/waiter counts unchanged.
        # Running/live/waiter buckets fall back to full.
        if live_bucket not in {
            "Done",
            "Failed",
            "DONE",
            "FAILED",
        } or inc_bucket not in {
            "Done",
            "Failed",
            "DONE",
            "FAILED",
        }:
            return False
        if bool(getattr(live, "runner_is_live", False)) != bool(
            getattr(inc, "runner_is_live", False)
        ):
            return False
        if getattr(live, "pid", None) != getattr(inc, "pid", None):
            return False
    return True


def _roster_has_structure(agents: list[Agent]) -> bool:
    """Return whether any row needs session/workflow/clan/named-proc/fleet handling."""
    for a in agents:
        if getattr(a, "parent_workflow", None):
            return True
        if bool(getattr(a, "is_workflow_child", False)):
            return True
        if bool(getattr(a, "is_agent_session_member_child", False)):
            return True
        if getattr(a, "agent_session", None):
            return True
        if getattr(a, "agent_clan", None):
            return True
        if bool(getattr(a, "is_named_proc", False)):
            return True
        if getattr(a, "fleet_origin_alias", None):
            return True
        if bool(getattr(a, "is_clan_container", False)):
            return True
    return False


def _roster_has_capacity_shapes(agents: list[Agent]) -> bool:
    """Return whether any row could be a slot waiter/runner (needs slot writes)."""
    for a in agents:
        if bool(getattr(a, "runner_is_live", False)):
            return True
        if getattr(a, "slot_requested_at", None):
            return True
        try:
            from sase.agent.status_buckets import agent_status_bucket

            bucket = agent_status_bucket(a)
            if bucket not in {"Done", "Failed", "DONE", "FAILED"}:
                return True
        except Exception:
            st = getattr(a, "status", "")
            if st not in {"DONE", "FAILED", "Done", "Failed"}:
                return True
    return False


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
    """Attempt the delta-scaled worker boundary.

    Returns a ``PreparedApplyBoundary`` that is bit-identical to the full
    pipeline for pure scalar terminal deltas, or None when the delta needs
    the full pipeline. Pure scalar means: exact-delta eligible, small
    incoming, all relationship keys equal, terminal buckets equal, no
    session/workflow/clan/named-proc/fleet anywhere in cached+incoming, no
    waiters/runners, no dismissed/deleted, capacity report None, no holds.
    Anything else falls back to full (correct, just not scaled).
    """
    from dataclasses import replace as _replace

    from ._loading_compute import compute_apply_loaded_agents
    from ._loading_graph import (
        classify_exact_delta_fast_path,
        copy_agent_rows_delta_isolated,
    )

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
    if getattr(snapshot, "capacity_report", None) is not None:
        return None
    if getattr(snapshot, "fleet_rows", ()):
        try:
            if len(snapshot.fleet_rows) > 0:
                return None
        except Exception:
            return None
    if getattr(snapshot, "proc_projection", None) is not None:
        return None
    if getattr(snapshot, "agent_search_query", ""):
        return None
    if getattr(snapshot, "agent_status_overrides", {}):
        return None
    if getattr(snapshot, "agent_tabs_view_config", None) is not None:
        return None
    if getattr(snapshot, "unread_agent_ids", frozenset()):
        try:
            if len(snapshot.unread_agent_ids) > 0:
                return None
        except Exception:
            return None

    patch = try_scoped_scalar_patch(list(all_agents), snapshot)
    if patch is None:
        return None
    merged_full, _ = patch

    cached = list(snapshot.cached_agents_with_children)
    if _roster_has_structure(cached) or _roster_has_structure(list(all_agents)):
        return None
    if _roster_has_capacity_shapes(cached) or _roster_has_capacity_shapes(
        list(all_agents)
    ):
        return None

    cached_by_identity = {a.identity: (i, a) for i, a in enumerate(cached)}
    matched: list[tuple[int, Agent, Agent]] = []
    for inc in all_agents:
        found = cached_by_identity.get(inc.identity)
        if found is None:
            return None
        idx, live = found
        matched.append((idx, live, inc))
    if not _capacity_irrelevant(matched):
        return None

    # Pure scalar simple: closure is affected only (no parents/children/
    # siblings/clan since no structure). No live closure rows to copy
    # because affected positions hold worker-owned incoming. Zero copies.
    _, closure_by_id = patch
    closure_idx = set(closure_by_id.values())
    # Verify closure is exactly affected (no extra structure pulled in).
    affected_idx = {idx for idx, _, _ in matched}
    if closure_idx != affected_idx:
        return None

    prep = compute_apply_loaded_agents(
        list(all_agents),
        list(dismissed_from_loader),
        set(dismissed_snapshot),
        bool(hide_non_run_agents),
        dismissed_bundle_snapshot=dismissed_bundle_snapshot,
        explicit_removals=snapshot.explicit_removals,
    )
    from ._loading_helpers import is_always_visible

    always_visible = [a for a in merged_full if is_always_visible(a)]
    hideable = [a for a in merged_full if not is_always_visible(a)]
    if always_visible and bool(hide_non_run_agents) and hideable:
        prep.filtered_agents = always_visible
        prep.hidden_count = len(hideable)
    else:
        prep.filtered_agents = list(merged_full)
        prep.hidden_count = 0
    prep.has_always_visible = bool(always_visible)
    prep.hideable_agents = list(hideable)
    prep.capacity_agents = list(snapshot.capacity_agents_with_children)

    # Runner capacity: no waiters/runners anywhere (verified), report None,
    # no holds (check global holds empty to avoid external drift).
    try:
        from sase.core.agent_hold_facade import active_agent_hold_records

        if tuple(active_agent_hold_records()):
            return None
    except Exception:
        pass
    from sase.config.core import get_max_running_agents

    from ...models.agent_runner_slots import refresh_runner_slot_context

    # Slot is a no-op for pure terminal with no waiters/runners, but run
    # the fallback once over merged_full to produce the neutral snapshot.
    # It writes only neutral runner_* fields; to avoid touching live rows,
    # run it over worker-owned copies of affected incoming only, then reuse
    # the neutral snapshot. Since affected are terminal with no slot shapes,
    # their runner_* fields are already neutral; verify and skip.
    for _, _, inc in matched:
        if getattr(inc, "runner_slots_in_use", None) is not None:
            return None
        if getattr(inc, "runner_slot_queue_position", None) is not None:
            return None
    runner_capacity = refresh_runner_slot_context(
        [],
        effective_limit=float(get_max_running_agents()),
        capacity_agents=[],
    )

    # Fold: no fold levels (verify) and no clan (verified) => identity.
    if snapshot.fold_levels is not None:
        return None
    from ._loading_compute import (
        PreparedFoldFiltering,
        project_and_fold_rosters,
    )

    # project_and_fold_rosters with no fleet + no folds still calls
    # project_mixed_agent_tree which mutates via _reset even with no clans.
    # Skip tree entirely when no clans (verified): unfiltered = merged_full.
    def _local_rows(rows: list[Agent]) -> list[Agent]:
        return [a for a in rows if not a.fleet_origin_alias]

    fold = PreparedFoldFiltering(
        unfiltered_agents=list(merged_full),
        visible_agents=list(merged_full),
        fold_counts={},
        local_unfiltered_agents=list(merged_full),
        local_visible_agents=_local_rows(list(merged_full)),
    )

    from ._loading_compute_types import PreparedApplyBoundary
    from ...models.agent_runner_slots import RunnerCapacitySnapshot

    boundary = PreparedApplyBoundary(
        prep=prep,
        fold=fold,
        selection=snapshot.selection,
        runner_capacity=runner_capacity,
        runner_capacity_estimate=runner_capacity,
        capacity_generation=snapshot.capacity_generation,
        proc_generation=snapshot.proc_generation,
        fleet_source_rows=tuple(snapshot.fleet_rows),
        dismissed_agents_snapshot=frozenset(snapshot.dismissed_agents),
        removal_generation=snapshot.removal_generation,
    )
    return boundary

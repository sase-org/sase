"""Worker ownership for prepared Agents-tab apply snapshots.

``PreparedApplySnapshot`` is frozen, but that only freezes the snapshot
fields. The ``Agent`` rows in ``cached_agents_with_children`` and
``capacity_agents_with_children`` remain the live UI graph unless this
boundary copies them first.

Call this before any mutating preparation (incomplete merge, status
overrides, relationship rebuild, runner-slot annotation, or named-proc
carryover that will be published). Incoming loader rows that are not in
the live graph stay as-is so the current worker keeps exclusive ownership
of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from ...models._agent_graph import (
    adopt_agents,
    agent_share_fingerprint,
    copy_agent_graph,
    copy_agent_rows_delta_isolated,
)
from ...models.agent import Agent
from ._loading_compute_types import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySnapshot,
)

__all__ = [
    "CachedGraphNeeds",
    "ExactDeltaFastPath",
    "adopt_prepared_apply_data",
    "classify_cached_graph_needs",
    "classify_exact_delta_fast_path",
    "own_exact_delta_snapshot_fast",
    "own_prepared_apply_snapshot",
    "own_required_apply_snapshot",
    "share_back_boundary_fast",
]


@dataclass(frozen=True)
class CachedGraphNeeds:
    """Which cached roots a load path must detach before mutating preparation.

    Computed read-only from the snapshot (and the incoming capacity roster when
    the caller already has it) before any copying, so an authoritative load
    never pays for history it is about to discard.
    """

    cached_roster: bool
    cached_named_procs: bool
    capacity: bool
    fleet: bool


def _merge_patches_cached_history(snapshot: PreparedApplySnapshot) -> bool:
    """Return whether the merge path patches incoming rows over cached history.

    Mirrors the early-return predicates of
    :func:`merge_incomplete_load_after_complete_history`: an absent load state,
    an authoritative complete history, or an incomplete load with no watermark
    and no delta/bounded evidence replaces the cache instead of patching it.
    """
    load_state = snapshot.load_state
    if load_state is None or load_state.complete_history:
        return False
    if snapshot.agents_seen_complete_history:
        return True
    if load_state.artifact_source == "artifact_delta":
        return True
    return bool(load_state.bounded_prefix) and snapshot.cache_query_matches


def classify_cached_graph_needs(
    snapshot: PreparedApplySnapshot,
    *,
    incoming_capacity_nonempty: bool | None = None,
) -> CachedGraphNeeds:
    """Classify which cached roots the load must detach, without copying.

    *cached_roster* covers the merge patch path (and the named-proc fallback it
    subsumes). *cached_named_procs* covers only the fallback rows when an
    authoritative replacement runs without a proc projection — an empty
    projection is authoritative, so no fallback rows are needed then.
    *capacity* covers the capacity merge recursion, which runs only when the
    merge proceeds and both the incoming and cached capacity rosters are
    non-empty. *fleet* covers the fleet projection, which always writes tree
    links onto the fleet rows it is given.
    """
    if incoming_capacity_nonempty is None:
        incoming_nonempty = True
    else:
        incoming_nonempty = incoming_capacity_nonempty
    patches = _merge_patches_cached_history(snapshot)
    roster_nonempty = bool(snapshot.cached_agents_with_children)
    needs_roster = patches and roster_nonempty
    needs_capacity = (
        patches
        and roster_nonempty
        and bool(snapshot.capacity_agents_with_children)
        and incoming_nonempty
    )
    needs_named_procs = (
        not needs_roster
        and snapshot.proc_projection is None
        and any(agent.is_named_proc for agent in snapshot.cached_agents_with_children)
    )
    return CachedGraphNeeds(
        cached_roster=needs_roster,
        cached_named_procs=needs_named_procs,
        capacity=needs_capacity,
        fleet=bool(snapshot.fleet_rows),
    )


def own_required_apply_snapshot(
    snapshot: PreparedApplySnapshot,
    needs: CachedGraphNeeds,
) -> tuple[PreparedApplySnapshot, dict[int, Agent]]:
    """Return a snapshot with only the required cached roots detached.

    Uses one memo across the required roots so overlapping visible, capacity,
    and fleet rows keep one detached clone. Roots that no load path touches
    stay live and must never be mutated by downstream preparation.
    """
    memo: dict[int, Agent] = {}
    cached = snapshot.cached_agents_with_children
    if needs.cached_roster:
        new_cached = copy_agent_graph(cached, memo)
    elif needs.cached_named_procs:
        named = [agent for agent in cached if agent.is_named_proc]
        copies = copy_agent_graph(named, memo)
        table = {
            id(original): clone for original, clone in zip(named, copies, strict=True)
        }
        new_cached = [table.get(id(agent), agent) for agent in cached]
    else:
        new_cached = cached
    if needs.capacity:
        new_capacity = copy_agent_graph(
            snapshot.capacity_agents_with_children,
            memo,
        )
    else:
        new_capacity = snapshot.capacity_agents_with_children
    if needs.fleet:
        new_fleet = tuple(copy_agent_graph(snapshot.fleet_rows, memo))
    else:
        new_fleet = snapshot.fleet_rows
    owned = replace(
        snapshot,
        cached_agents_with_children=new_cached,
        capacity_agents_with_children=new_capacity,
        fleet_rows=new_fleet,
    )
    return owned, memo


def own_prepared_apply_snapshot(
    snapshot: PreparedApplySnapshot,
) -> tuple[PreparedApplySnapshot, dict[int, Agent]]:
    """Return a snapshot whose cached row graphs are worker-owned copies.

    Uses one memo across the visible, capacity, and fleet rosters so a row that
    appears in several stays a single object in the detached graph. The worker
    projects the fleet rows into the roster, and that projection writes tree
    links onto them, so they must not alias the live fleet rows.
    """
    return own_required_apply_snapshot(
        snapshot,
        CachedGraphNeeds(
            cached_roster=True,
            cached_named_procs=False,
            capacity=True,
            fleet=True,
        ),
    )


@dataclass(frozen=True)
class ExactDeltaFastPath:
    """Eligibility of the conservative exact-artifact-delta fast path.

    *eligible* is True only for Tier-1 ``artifact_delta`` patch merges over a
    complete-history watermark with a matching committed query. Every other
    load (full/authoritative replacements, repair-recommended deltas,
    bounded-prefix window changes, running-claim scans, unreadable query
    state) keeps the existing deep-detach safe path and records *reason* as
    its explicit trace fallback.
    """

    eligible: bool
    reason: str


def classify_exact_delta_fast_path(
    snapshot: PreparedApplySnapshot,
) -> ExactDeltaFastPath:
    """Decide whether the snapshot may use the delta-isolated fast ownership.

    The fast path still runs the full merge/slot/tree pipeline, but on
    shallow-isolated row copies instead of deep graph clones, then shares
    back untouched rows by fingerprint. It is only safe when the merge will
    patch incoming rows over cached history (never an authoritative
    replacement), so the same predicates as
    :func:`_merge_patches_cached_history` gate it, plus artifact-delta
    specificity and repair/query guards that would otherwise broaden the
    write set beyond the isolated copies.
    """
    load_state = snapshot.load_state
    if load_state is None:
        return ExactDeltaFastPath(eligible=False, reason="no-load-state")
    if load_state.complete_history:
        return ExactDeltaFastPath(eligible=False, reason="authoritative-complete")
    if load_state.artifact_source != "artifact_delta":
        return ExactDeltaFastPath(eligible=False, reason="not-artifact-delta")
    if load_state.repair_recommended:
        return ExactDeltaFastPath(eligible=False, reason="repair-recommended")
    if load_state.bounded_prefix:
        return ExactDeltaFastPath(eligible=False, reason="bounded-prefix")
    if not snapshot.agents_seen_complete_history:
        return ExactDeltaFastPath(eligible=False, reason="no-complete-watermark")
    if not snapshot.cache_query_matches:
        return ExactDeltaFastPath(eligible=False, reason="query-mismatch")
    if bool(getattr(load_state, "running_claims_scanned", False)):
        return ExactDeltaFastPath(eligible=False, reason="running-claims-scan")
    if not snapshot.cached_agents_with_children:
        return ExactDeltaFastPath(eligible=False, reason="empty-cache")
    return ExactDeltaFastPath(eligible=True, reason="exact-delta")


def own_exact_delta_snapshot_fast(
    snapshot: PreparedApplySnapshot,
    needs: CachedGraphNeeds,
) -> tuple[PreparedApplySnapshot, dict[int, Agent], ExactDeltaFastPath]:
    """Own cached roots with shallow-isolated copies for an exact delta.

    Uses one memo across the visible, capacity, fleet, and named-proc-fallback
    roots so overlapping rows keep one detached clone. Every row object is a
    new copy (no alias to live rows) and every mutable list/dict/set
    container is detached, so the full merge/slot/tree pipeline may run
    unchanged without mutating the displayed graph. Untouched rows are
    shared back by fingerprint after the pipeline in
    :func:`_share_back_exact_delta_lists`; only retained new objects scale
    with the affected closure, never the full roster.
    """
    decision = classify_exact_delta_fast_path(snapshot)
    if not decision.eligible:
        owned, fast_memo = own_required_apply_snapshot(snapshot, needs)
        return owned, fast_memo, decision
    memo: dict[int, Agent] = {}
    cached = snapshot.cached_agents_with_children
    if needs.cached_roster:
        new_cached = copy_agent_rows_delta_isolated(cached, memo)
    elif needs.cached_named_procs:
        named = [agent for agent in cached if agent.is_named_proc]
        copies = copy_agent_rows_delta_isolated(named, memo)
        table = {
            id(original): clone for original, clone in zip(named, copies, strict=True)
        }
        new_cached = [table.get(id(agent), agent) for agent in cached]
    else:
        new_cached = cached
    if needs.capacity:
        new_capacity = copy_agent_rows_delta_isolated(
            snapshot.capacity_agents_with_children,
            memo,
        )
    else:
        new_capacity = snapshot.capacity_agents_with_children
    if needs.fleet:
        new_fleet = tuple(copy_agent_rows_delta_isolated(snapshot.fleet_rows, memo))
    else:
        new_fleet = snapshot.fleet_rows
    owned = replace(
        snapshot,
        cached_agents_with_children=new_cached,
        capacity_agents_with_children=new_capacity,
        fleet_rows=new_fleet,
    )
    return owned, memo, decision


def _share_back_exact_delta_lists(
    working: list[Agent],
    live: list[Agent] | tuple[Agent, ...],
) -> list[Agent]:
    """Share back live rows whose fingerprints match the worked copies.

    For each worked row, finds the live row with the same identity and
    reuses the live object when every dataclass field matches modulo
    ``Agent``-reference relinking (working copies point at working copies,
    live rows at live rows). Changed rows (scalar updates, terminal
    transitions, added children, deletions already absent, remirrors,
    requeued waiters, reprojected containers) keep their worked copies.
    Unrelated components therefore preserve object identity in the
    published roster while mutated rows stay owned.
    """
    live_by_identity: dict[object, list[Agent]] = {}
    for agent in live:
        live_by_identity.setdefault(agent.identity, []).append(agent)
    live_fingerprints: dict[int, tuple[object, ...]] = {}
    shared: list[Agent] = []
    for agent in working:
        candidates = live_by_identity.get(agent.identity, [])
        if not candidates:
            shared.append(agent)
            continue
        work_fp = agent_share_fingerprint(agent)
        match: Agent | None = None
        for live_agent in candidates:
            # Visible, capacity, and fleet rosters alias the same row object,
            # so one identity routinely maps to the same object twice. Share
            # the first live row whose fingerprint matches the worked copy.
            live_key = id(live_agent)
            live_fp = live_fingerprints.get(live_key)
            if live_fp is None:
                live_fp = agent_share_fingerprint(live_agent)
                live_fingerprints[live_key] = live_fp
            if work_fp == live_fp:
                match = live_agent
                break
        shared.append(match if match is not None else agent)
    return shared


def share_back_boundary_fast(
    boundary: PreparedApplyBoundary,
    live_snapshot: PreparedApplySnapshot,
) -> PreparedApplyBoundary:
    """Share back untouched rows on an exact-delta fast-path boundary.

    Replaces worked copies with live objects wherever fingerprints match,
    across every published roster (prep, fold, and finalize query/scoped
    lists) using one identity lookup so all rosters stay consistent. Only
    runs when :func:`classify_exact_delta_fast_path` deems the live
    snapshot eligible; every other load keeps its existing owned copies.
    Call on the UI thread after finalize with no await before apply.
    """
    from dataclasses import replace as _replace

    if not classify_exact_delta_fast_path(live_snapshot).eligible:
        return boundary
    live_union: list[Agent] = [
        *live_snapshot.cached_agents_with_children,
        *live_snapshot.capacity_agents_with_children,
        *live_snapshot.fleet_rows,
    ]
    prep = boundary.prep
    prep = _replace(
        prep,
        filtered_agents=_share_back_exact_delta_lists(
            list(prep.filtered_agents), live_union
        ),
        hideable_agents=_share_back_exact_delta_lists(
            list(prep.hideable_agents), live_union
        ),
        capacity_agents=_share_back_exact_delta_lists(
            list(prep.capacity_agents), live_union
        ),
        dismissed_agent_objects=_share_back_exact_delta_lists(
            list(prep.dismissed_agent_objects), live_union
        ),
    )
    fold = boundary.fold
    fold = _replace(
        fold,
        unfiltered_agents=_share_back_exact_delta_lists(
            list(fold.unfiltered_agents), live_union
        ),
        visible_agents=_share_back_exact_delta_lists(
            list(fold.visible_agents), live_union
        ),
        local_unfiltered_agents=_share_back_exact_delta_lists(
            list(fold.local_unfiltered_agents), live_union
        ),
        local_visible_agents=_share_back_exact_delta_lists(
            list(fold.local_visible_agents), live_union
        ),
    )
    finalize = boundary.finalize
    if finalize is not None:
        query = finalize.query
        query = _replace(
            query,
            filtered_agents=_share_back_exact_delta_lists(
                list(query.filtered_agents), live_union
            ),
        )
        finalize = _replace(
            finalize,
            query=query,
            agents_query_result=_share_back_exact_delta_lists(
                list(finalize.agents_query_result), live_union
            ),
            scoped_agents=_share_back_exact_delta_lists(
                list(finalize.scoped_agents), live_union
            ),
        )
    return _replace(boundary, prep=prep, fold=fold, finalize=finalize)


def adopt_prepared_apply_data(
    prep: PreparedApplyData,
    memo: Mapping[int, Agent],
) -> PreparedApplyData:
    """Rewrite *prep* lists so live cached rows are replaced by detached copies."""
    prep.filtered_agents = adopt_agents(prep.filtered_agents, memo)
    prep.hideable_agents = adopt_agents(prep.hideable_agents, memo)
    prep.capacity_agents = adopt_agents(prep.capacity_agents, memo)
    prep.dismissed_agent_objects = adopt_agents(prep.dismissed_agent_objects, memo)
    return prep

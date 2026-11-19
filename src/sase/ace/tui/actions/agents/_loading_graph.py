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
from dataclasses import dataclass, fields, replace

from ...models._agent_graph import (
    AGENT_RELINK_FIELDS,
    adopt_agents,
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


_AGENT_NON_RELINK_FIELDS = tuple(
    field.name for field in fields(Agent) if field.name not in AGENT_RELINK_FIELDS
)


def _same_share_back_fields(working: Agent, live: Agent) -> bool:
    """Compare non-link fields, using shallow-copy identity as the fast path."""
    for name in _AGENT_NON_RELINK_FIELDS:
        working_value = getattr(working, name)
        live_value = getattr(live, name)
        if working_value is live_value:
            continue
        try:
            if working_value != live_value:
                return False
        except Exception:  # noqa: BLE001 - an incomparable field cannot be shared.
            return False
    return True


def _agent_relink_pairs(
    working_value: object,
    live_value: object,
) -> list[tuple[Agent, Agent]] | None:
    """Return positional Agent-reference pairs, or None for a shape mismatch."""
    if isinstance(working_value, Agent) or isinstance(live_value, Agent):
        if isinstance(working_value, Agent) and isinstance(live_value, Agent):
            return [(working_value, live_value)]
        return None
    if isinstance(working_value, (list, tuple)) or isinstance(
        live_value, (list, tuple)
    ):
        if not isinstance(working_value, (list, tuple)) or not isinstance(
            live_value, (list, tuple)
        ):
            return None
        if len(working_value) != len(live_value):
            return None
        pairs: list[tuple[Agent, Agent]] = []
        for working_item, live_item in zip(working_value, live_value, strict=True):
            if isinstance(working_item, Agent) or isinstance(live_item, Agent):
                if not isinstance(working_item, Agent) or not isinstance(
                    live_item, Agent
                ):
                    return None
                pairs.append((working_item, live_item))
            elif working_item is not live_item:
                try:
                    if working_item != live_item:
                        return None
                except Exception:  # noqa: BLE001 - an incomparable value differs.
                    return None
        return pairs
    if working_value is live_value:
        return []
    try:
        return [] if working_value == live_value else None
    except Exception:  # noqa: BLE001 - an incomparable value differs.
        return None


def _boundary_agent_lists(boundary: PreparedApplyBoundary) -> list[list[Agent]]:
    """Return every Agent list whose rows are published from this boundary."""
    lists = [
        boundary.prep.filtered_agents,
        boundary.prep.hideable_agents,
        boundary.prep.capacity_agents,
        boundary.prep.dismissed_agent_objects,
        boundary.fold.unfiltered_agents,
        boundary.fold.visible_agents,
        boundary.fold.local_unfiltered_agents,
        boundary.fold.local_visible_agents,
    ]
    if boundary.finalize is not None:
        lists.extend(
            (
                boundary.finalize.query.filtered_agents,
                boundary.finalize.agents_query_result,
                boundary.finalize.scoped_agents,
            )
        )
    return lists


def _reachable_boundary_agents(boundary_lists: list[list[Agent]]) -> dict[int, Agent]:
    """Collect each row published directly or through a relink field once."""
    rows: dict[int, Agent] = {}
    pending = [agent for agents in boundary_lists for agent in agents]
    while pending:
        agent = pending.pop()
        key = id(agent)
        if key in rows:
            continue
        rows[key] = agent
        for name in AGENT_RELINK_FIELDS:
            value = getattr(agent, name)
            if isinstance(value, Agent):
                pending.append(value)
            elif isinstance(value, (list, tuple)):
                pending.extend(item for item in value if isinstance(item, Agent))
    return rows


def share_back_boundary_fast(
    boundary: PreparedApplyBoundary,
    live_snapshot: PreparedApplySnapshot,
) -> PreparedApplyBoundary:
    """Share unchanged rows back while preserving aliases across the graph.

    Each distinct worked row is compared once, then candidate sharing is
    closed over ``AGENT_RELINK_FIELDS``. Rows that remain worker-owned have
    their links rewritten through the final decision map, so no published
    row can retain an orphaned worked copy. This runs in the final worker
    step before the UI-thread apply seam.
    """
    if not classify_exact_delta_fast_path(live_snapshot).eligible:
        return boundary

    published_lists = _boundary_agent_lists(boundary)
    working_rows = _reachable_boundary_agents(published_lists)
    live_rows: dict[int, Agent] = {}
    live_by_identity: dict[object, Agent] = {}
    for agent in (
        *live_snapshot.cached_agents_with_children,
        *live_snapshot.capacity_agents_with_children,
        *live_snapshot.fleet_rows,
    ):
        live_rows.setdefault(id(agent), agent)
        live_by_identity.setdefault(agent.identity, agent)
    keep_named_proc_copies = classify_cached_graph_needs(
        live_snapshot
    ).cached_named_procs

    # Start optimistic: each row resolves to its one live identity match only
    # when every non-link field is equal. Missing or changed rows resolve to
    # themselves and cannot be accidentally shared through another list.
    decisions: dict[int, Agent] = {}
    for key, working_agent in working_rows.items():
        if keep_named_proc_copies and working_agent.is_named_proc:
            decisions[key] = working_agent
            continue
        live_agent = live_by_identity.get(working_agent.identity)
        if live_agent is working_agent:
            decisions[key] = working_agent
        elif live_agent is not None and _same_share_back_fields(
            working_agent, live_agent
        ):
            decisions[key] = live_agent
        else:
            decisions[key] = working_agent

    # A row can be shared only while every link resolves to the exact object
    # its live counterpart references. Record those dependencies once, then
    # propagate any unshare decision through the reverse edges in linear time.
    unshared: set[int] = set()
    dependents: dict[int, set[int]] = {}
    for source_key, working_agent in working_rows.items():
        live_agent = decisions[source_key]
        if live_agent is working_agent:
            continue
        for name in AGENT_RELINK_FIELDS:
            pairs = _agent_relink_pairs(
                getattr(working_agent, name), getattr(live_agent, name)
            )
            if pairs is None:
                unshared.add(source_key)
                break
            for working_ref, live_ref in pairs:
                target_key = id(working_ref)
                if target_key not in decisions:
                    if working_ref is not live_ref:
                        unshared.add(source_key)
                        break
                    continue
                target_decision = decisions[target_key]
                if target_decision is not live_ref:
                    unshared.add(source_key)
                    break
                if target_decision is not working_ref:
                    dependents.setdefault(target_key, set()).add(source_key)
            if source_key in unshared:
                break

    pending_unshare = list(unshared)
    while pending_unshare:
        target_key = pending_unshare.pop()
        for source_key in dependents.get(target_key, ()):
            if source_key not in unshared:
                unshared.add(source_key)
                pending_unshare.append(source_key)

    for key in unshared:
        decisions[key] = working_rows[key]

    # Owned copies get fresh list containers and links to the objects chosen
    # above. Live rows are never mutated by this repair.
    live_ids = set(live_rows)
    for key, agent in working_rows.items():
        if decisions[key] is not agent or key in live_ids:
            continue
        for name in AGENT_RELINK_FIELDS:
            value = getattr(agent, name)
            if isinstance(value, Agent):
                setattr(agent, name, decisions.get(id(value), value))
            elif isinstance(value, list):
                setattr(
                    agent,
                    name,
                    [
                        decisions.get(id(item), item)
                        if isinstance(item, Agent)
                        else item
                        for item in value
                    ],
                )

    def publish(rows: list[Agent]) -> list[Agent]:
        return [decisions.get(id(agent), agent) for agent in rows]

    prep = boundary.prep
    prep = replace(
        prep,
        filtered_agents=publish(prep.filtered_agents),
        hideable_agents=publish(prep.hideable_agents),
        capacity_agents=publish(prep.capacity_agents),
        dismissed_agent_objects=publish(prep.dismissed_agent_objects),
    )
    fold = boundary.fold
    fold = replace(
        fold,
        unfiltered_agents=publish(fold.unfiltered_agents),
        visible_agents=publish(fold.visible_agents),
        local_unfiltered_agents=publish(fold.local_unfiltered_agents),
        local_visible_agents=publish(fold.local_visible_agents),
    )
    finalize = boundary.finalize
    if finalize is not None:
        query = finalize.query
        query = replace(
            query,
            filtered_agents=publish(query.filtered_agents),
        )
        finalize = replace(
            finalize,
            query=query,
            agents_query_result=publish(finalize.agents_query_result),
            scoped_agents=publish(finalize.scoped_agents),
        )
    return replace(boundary, prep=prep, fold=fold, finalize=finalize)


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

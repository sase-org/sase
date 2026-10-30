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

from ...models._agent_graph import adopt_agents, copy_agent_graph
from ...models.agent import Agent
from ._loading_compute_types import PreparedApplyData, PreparedApplySnapshot

__all__ = [
    "CachedGraphNeeds",
    "adopt_prepared_apply_data",
    "classify_cached_graph_needs",
    "own_prepared_apply_snapshot",
    "own_required_apply_snapshot",
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

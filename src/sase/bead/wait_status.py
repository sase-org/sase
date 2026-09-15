"""Owner-aware status resolution for bead wait dependencies."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sase.bead.cross_project import (
    BeadStoreSnapshot,
    bead_id_prefix,
    enabled_project_store_snapshots,
)
from sase.core.bead_target_routing_facade import (
    BeadTargetRoute,
    BeadTargetStoreDescriptor,
    route_bead_targets,
)

type ClosedIdsResolver = Callable[[str], frozenset[str] | None]
type SyncHint = Callable[[str | None], None]


@dataclass
class WaitBeadStatusCache:
    """Per-pass cache for wait-bead store snapshots and closed-ID reads."""

    closed_by_project: dict[str, frozenset[str] | None] = field(default_factory=dict)
    snapshots: tuple[BeadStoreSnapshot, ...] | None = None


@dataclass(frozen=True)
class _WaitBeadStatus:
    """Closed wait IDs plus routed owner projects observed while checking."""

    closed_ids: frozenset[str] | None
    owner_projects: frozenset[str] = frozenset()


def closed_bead_ids_for_waits(
    project_name: str | None,
    wait_beads: Iterable[object],
    *,
    cache: WaitBeadStatusCache | None = None,
    closed_ids_for_project: ClosedIdsResolver | None = None,
    sync_hint: SyncHint | None = None,
) -> _WaitBeadStatus:
    """Return the requested bead waits that are currently closed.

    Shorthand and future-bead waits keep the waiting agent's project scope.
    Full IDs that are not already closed locally are routed through the same
    enabled-project snapshot policy used by bead commands; unresolved foreign
    waits simply stay absent from ``closed_ids`` so the caller remains parked.
    """

    wait_ids = tuple(bead for bead in wait_beads if isinstance(bead, str) and bead)
    if not wait_ids:
        return _WaitBeadStatus(frozenset())

    status_cache = cache or WaitBeadStatusCache()
    resolver = closed_ids_for_project or _closed_bead_ids_for_project
    closed_ids: set[str] = set()
    owner_projects: set[str] = set()

    local_closed = None
    if project_name:
        local_closed = _closed_ids_for_project(
            project_name,
            cache=status_cache,
            resolver=resolver,
        )
        if local_closed is not None:
            closed_ids.update(local_closed)

    full_ids = [
        bead_id
        for bead_id in wait_ids
        if bead_id_prefix(bead_id) is not None and bead_id not in closed_ids
    ]
    if not full_ids:
        return _WaitBeadStatus(frozenset(closed_ids), frozenset(owner_projects))

    snapshots = _enabled_snapshots(status_cache)
    local_store = _local_store_descriptor(project_name, snapshots)
    candidate_stores = [
        snapshot.descriptor()
        for snapshot in snapshots
        if local_store is None or snapshot.store_key != local_store.store_key
    ]
    outcome = route_bead_targets(
        full_ids,
        local_store=local_store,
        candidate_stores=candidate_stores,
        require_single_store=False,
    )
    for route in outcome.routes:
        owner_project = _route_owner_project(route, fallback_project=project_name)
        if owner_project:
            owner_projects.add(owner_project)
            _hint_owner(owner_project, sync_hint)
        elif route.error is not None:
            for candidate in route.error.candidates:
                if candidate.project_key:
                    owner_projects.add(candidate.project_key)
                    _hint_owner(candidate.project_key, sync_hint)
        if route.error is not None or route.resolved_id is None:
            continue
        if owner_project is None:
            continue
        owner_closed = _closed_ids_for_project(
            owner_project,
            cache=status_cache,
            resolver=resolver,
        )
        if owner_closed is None:
            continue
        if route.resolved_id in owner_closed:
            closed_ids.add(route.requested_id)
            closed_ids.add(route.resolved_id)

    return _WaitBeadStatus(frozenset(closed_ids), frozenset(owner_projects))


def _closed_bead_ids_for_project(project_name: str) -> frozenset[str] | None:
    from sase.bead.store_locator import closed_bead_ids_for_project

    return closed_bead_ids_for_project(project_name)


def _closed_ids_for_project(
    project_name: str,
    *,
    cache: WaitBeadStatusCache,
    resolver: ClosedIdsResolver,
) -> frozenset[str] | None:
    if project_name not in cache.closed_by_project:
        cache.closed_by_project[project_name] = resolver(project_name)
    return cache.closed_by_project[project_name]


def _enabled_snapshots(
    cache: WaitBeadStatusCache,
) -> tuple[BeadStoreSnapshot, ...]:
    if cache.snapshots is None:
        cache.snapshots = enabled_project_store_snapshots()
    return cache.snapshots


def _local_store_descriptor(
    project_name: str | None,
    snapshots: tuple[BeadStoreSnapshot, ...],
) -> BeadTargetStoreDescriptor | None:
    if not project_name:
        return None
    folded = project_name.casefold()
    for snapshot in snapshots:
        refs = {ref.casefold() for ref in snapshot.project_refs}
        refs.add(snapshot.origin.project_key.casefold())
        if folded in refs:
            return snapshot.descriptor()
    return None


def _route_owner_project(
    route: BeadTargetRoute,
    *,
    fallback_project: str | None,
) -> str | None:
    if route.store is None:
        return None
    if route.store.project_key:
        return route.store.project_key
    return fallback_project


def _hint_owner(project_name: str, sync_hint: SyncHint | None) -> None:
    if sync_hint is None:
        return
    sync_hint(project_name)


__all__ = [
    "WaitBeadStatusCache",
    "closed_bead_ids_for_waits",
]

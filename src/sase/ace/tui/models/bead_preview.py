"""Store directory, routing, and preview loading for prompt bead cards.

Callers must run the I/O entry points (``load_bead_store_directory``,
``route_bead_mention``, ``load_bead_preview``) off the UI thread.
``BeadStoreDirectory.owners_for_prefix`` and ``owns_prefix`` are memory
only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sase.bead.cross_project import (
    BeadStoreSnapshot,
    bead_id_prefix,
    enabled_project_store_snapshots,
    probe_bead_target_owner,
    route_full_id_with_snapshots,
)
from sase.bead.model import Issue, IssueType
from sase.core.bead_read_facade import show_issue_detail

PlanSource = Literal["self", "parent"]


class _RoutedStore(Protocol):
    """Structural type for a frozen Rust routing result store."""

    @property
    def store_key(self) -> str: ...

    @property
    def project_key(self) -> str | None: ...

    @property
    def project_label(self) -> str | None: ...

    @property
    def primary_workspace(self) -> Path | None: ...

    @property
    def beads_dir(self) -> Path | None: ...


@dataclass(frozen=True)
class BeadStoreRef:
    """One enabled project's canonical bead store, ready for a preview load."""

    project_key: str
    project_label: str
    beads_dir: Path
    primary_workspace: Path


@dataclass(frozen=True)
class BeadStoreDirectory:
    """Warm, memory-only snapshot of every enabled project's bead store."""

    snapshots: tuple[BeadStoreSnapshot, ...] = ()

    def __post_init__(self) -> None:
        snapshots = self.snapshots
        if isinstance(snapshots, BeadStoreSnapshot):
            object.__setattr__(self, "snapshots", (snapshots,))
            return
        object.__setattr__(self, "snapshots", tuple(snapshots))

    def owns_prefix(self, prefix: str) -> bool:
        """Return whether any snapshot claims *prefix* (including unavailable)."""
        return bool(self._snapshots_for_prefix(prefix))

    def owners_for_prefix(self, prefix: str) -> tuple[BeadStoreRef, ...]:
        """Return materialized stores whose prefix or project refs match *prefix*."""
        owners: list[BeadStoreRef] = []
        seen: set[str] = set()
        for snapshot in self._snapshots_for_prefix(prefix):
            ref = _store_ref_from_snapshot(snapshot)
            if ref is None:
                continue
            key = str(ref.beads_dir)
            if key in seen:
                continue
            seen.add(key)
            owners.append(ref)
        return tuple(owners)

    def _snapshots_for_prefix(self, prefix: str) -> tuple[BeadStoreSnapshot, ...]:
        folded = prefix.casefold()
        matches: list[BeadStoreSnapshot] = []
        for snapshot in self.snapshots:
            issue_prefix = snapshot.issue_prefix
            if issue_prefix is not None and issue_prefix.casefold() == folded:
                matches.append(snapshot)
                continue
            if any(ref.casefold() == folded for ref in snapshot.project_refs):
                matches.append(snapshot)
        return tuple(matches)

    def store_for_route(self, route_store: _RoutedStore) -> BeadStoreRef | None:
        """Map a routing result store back onto a ``BeadStoreRef``."""
        beads_dir = route_store.beads_dir
        project_key = route_store.project_key
        for snapshot in self.snapshots:
            origin = snapshot.origin
            if origin.beads_dir is None:
                continue
            if beads_dir is not None and origin.beads_dir == beads_dir:
                return _store_ref_from_snapshot(snapshot)
            if project_key and origin.project_key == project_key:
                return _store_ref_from_snapshot(snapshot)
        if beads_dir is None:
            return None
        return BeadStoreRef(
            project_key=project_key or "",
            project_label=route_store.project_label or project_key or "",
            beads_dir=beads_dir,
            primary_workspace=route_store.primary_workspace or beads_dir.parent,
        )


def load_bead_store_directory() -> BeadStoreDirectory:
    """Build a directory from the current enabled-project store snapshots."""
    return BeadStoreDirectory(snapshots=enabled_project_store_snapshots())


@dataclass(frozen=True)
class BeadRouteFound:
    bead_id: str
    store: BeadStoreRef


@dataclass(frozen=True)
class BeadRouteMissing:
    bead_id: str
    project_labels: tuple[str, ...]


@dataclass(frozen=True)
class BeadRouteNotBead:
    bead_id: str


@dataclass(frozen=True)
class BeadRouteAmbiguous:
    bead_id: str
    project_labels: tuple[str, ...]


@dataclass(frozen=True)
class BeadRouteUnavailable:
    bead_id: str
    project_label: str
    reason: str


BeadRoute = (
    BeadRouteFound
    | BeadRouteMissing
    | BeadRouteNotBead
    | BeadRouteAmbiguous
    | BeadRouteUnavailable
)


def route_bead_mention(
    bead_id: str,
    directory: BeadStoreDirectory,
    *,
    project_ref: str | None = None,
) -> BeadRoute:
    """Route a full bead ID through *directory* without recording a bead read."""
    prefix = bead_id_prefix(bead_id)
    if prefix is None:
        return BeadRouteNotBead(bead_id)
    matching = directory._snapshots_for_prefix(prefix)
    if not matching:
        return BeadRouteNotBead(bead_id)

    route = route_full_id_with_snapshots(bead_id, directory.snapshots)
    if route is None:
        return BeadRouteNotBead(bead_id)

    if route.error is None and route.store is not None:
        store = directory.store_for_route(route.store)
        if store is None:
            return _missing_from_snapshots(bead_id, matching)
        return BeadRouteFound(bead_id, store)

    kind = route.error.kind if route.error is not None else ""
    if kind == "ambiguous":
        labels = _candidate_labels(route.error.candidates if route.error else ())
        pinned = _pin_ambiguous_store(
            bead_id,
            directory,
            project_ref=project_ref,
            candidates=route.error.candidates if route.error is not None else (),
        )
        if pinned is not None:
            return BeadRouteFound(bead_id, pinned)
        return BeadRouteAmbiguous(bead_id, labels)
    if kind == "unavailable":
        label = _first_label(matching)
        reason = route.error.message if route.error is not None else "unavailable"
        return BeadRouteUnavailable(bead_id, label, reason)
    return _missing_from_snapshots(bead_id, matching)


def _pin_ambiguous_store(
    bead_id: str,
    directory: BeadStoreDirectory,
    *,
    project_ref: str | None,
    candidates: tuple[_RoutedStore, ...],
) -> BeadStoreRef | None:
    if not project_ref:
        return None
    folded = project_ref.casefold()
    for candidate in candidates:
        keys = (
            candidate.project_key or "",
            candidate.project_label or "",
        )
        if folded not in {key.casefold() for key in keys if key}:
            continue
        store = directory.store_for_route(candidate)
        if store is None:
            continue
        status, _stem = probe_bead_target_owner(store.beads_dir, bead_id)
        if status == "hit":
            return store
    return None


def _missing_from_snapshots(
    bead_id: str,
    matching: tuple[BeadStoreSnapshot, ...],
) -> BeadRouteMissing:
    labels = tuple(
        snapshot.origin.project_label or snapshot.origin.project_key
        for snapshot in matching
    )
    return BeadRouteMissing(bead_id, labels)


def _first_label(matching: tuple[BeadStoreSnapshot, ...]) -> str:
    if not matching:
        return ""
    origin = matching[0].origin
    return origin.project_label or origin.project_key


def _candidate_labels(candidates: tuple[_RoutedStore, ...]) -> tuple[str, ...]:
    labels: list[str] = []
    for candidate in candidates:
        label = candidate.project_label or candidate.project_key or candidate.store_key
        if label:
            labels.append(label)
    return tuple(labels)


def _store_ref_from_snapshot(snapshot: BeadStoreSnapshot) -> BeadStoreRef | None:
    origin = snapshot.origin
    if origin.beads_dir is None:
        return None
    return BeadStoreRef(
        project_key=origin.project_key,
        project_label=origin.project_label,
        beads_dir=origin.beads_dir,
        primary_workspace=origin.primary_workspace,
    )


@dataclass(frozen=True)
class BeadPreview:
    """Loaded bead card payload, including inherited plan metadata."""

    issue: Issue
    ancestors: tuple[Issue | None, ...]
    children: tuple[Issue, ...]
    depends_on: tuple[Issue | None, ...]
    blocks: tuple[Issue, ...]
    store: BeadStoreRef
    plan_reference: str | None
    plan_source: PlanSource | None
    plan_path: str | None


def load_bead_preview(bead_id: str, store: BeadStoreRef) -> BeadPreview:
    """Read one bead's preview payload. Raises ``KeyError`` when missing."""
    detail = show_issue_detail(store.beads_dir, bead_id, include_links=False)
    issue = detail.issue
    plan_reference, plan_source = _resolve_plan_reference(issue, detail.ancestors)
    plan_path = _resolve_plan_path(plan_reference, store)
    return BeadPreview(
        issue=issue,
        ancestors=detail.ancestors,
        children=detail.children,
        depends_on=detail.depends_on,
        blocks=detail.blocks,
        store=store,
        plan_reference=plan_reference,
        plan_source=plan_source,
        plan_path=plan_path,
    )


def _resolve_plan_reference(
    issue: Issue,
    ancestors: tuple[Issue | None, ...],
) -> tuple[str | None, PlanSource | None]:
    if issue.design:
        return issue.design, "self"
    if issue.issue_type != IssueType.PHASE or not ancestors:
        return None, None
    parent = ancestors[0]
    if parent is None or parent.issue_type != IssueType.PLAN or not parent.design:
        return None, None
    return parent.design, "parent"


def _resolve_plan_path(plan_reference: str | None, store: BeadStoreRef) -> str | None:
    if not plan_reference:
        return None
    from sase.ace.tui.widgets.artifacts.beads_data_sources import resolve_plan_link
    from sase.bead.store_locator import canonical_plans_dir_for_project

    plans_root = canonical_plans_dir_for_project(store.project_key)
    resolved = resolve_plan_link(
        plan_reference,
        workspace_dir=str(store.primary_workspace),
        plans_root=plans_root,
    )
    if not resolved:
        return None
    path = Path(resolved)
    if not path.exists():
        return None
    return str(path)


__all__ = [
    "BeadPreview",
    "BeadRoute",
    "BeadRouteAmbiguous",
    "BeadRouteFound",
    "BeadRouteMissing",
    "BeadRouteNotBead",
    "BeadRouteUnavailable",
    "BeadStoreDirectory",
    "BeadStoreRef",
    "load_bead_preview",
    "load_bead_store_directory",
    "route_bead_mention",
]

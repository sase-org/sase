"""Store directory, routing, and preview loading for prompt bead cards.

Callers must run the I/O entry points (``load_bead_store_directory``,
``route_bead_mention``, ``load_bead_preview``) off the UI thread.
``BeadStoreDirectory.owners_for_prefix`` and ``owns_prefix`` are memory
only.
"""

from __future__ import annotations

from collections import OrderedDict
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

    def owned_prefixes(self) -> frozenset[str]:
        """Return every casefolded prefix the directory owns.

        Covers each snapshot's ``issue_prefix`` plus its ``project_refs``,
        matching the casefolded comparison in :meth:`owns_prefix`. Feed the
        result to ``sase.bead.mentions.scan_bead_mentions``.
        """
        owned: set[str] = set()
        for snapshot in self.snapshots:
            if snapshot.issue_prefix:
                owned.add(snapshot.issue_prefix.casefold())
            for ref in snapshot.project_refs:
                if ref:
                    owned.add(ref.casefold())
        return frozenset(owned)

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


#: Bound for the app-level bead-mention index (about 2048 entries, LRU).
BEAD_MENTION_INDEX_BOUND = 2048


@dataclass(frozen=True)
class BeadMentionEntry:
    """One resolved bead mention: status plus the store token behind it.

    ``status`` is the bead's status value, or ``None`` when the ID cannot be
    resolved for the current route. ``store_key`` is ``str(store.beads_dir)``
    and ``fingerprint_token`` is the store's ``store_fingerprint`` token at
    resolution time (``None`` when the store could not be fingerprinted or
    the status was seeded provisionally).
    """

    status: str | None
    store_key: str
    fingerprint_token: str | None


class BeadMentionIndex:
    """Bounded LRU map of bead ID and routing context to mention entries.

    Textual-free and I/O-free: callers compute fingerprints and statuses
    off-thread and publish here. ``lookup`` never schedules work, so the
    highlight path can call it per rebuild.
    """

    def __init__(self, bound: int = BEAD_MENTION_INDEX_BOUND) -> None:
        self._bound = max(1, bound)
        self._entries: OrderedDict[tuple[str, str | None], BeadMentionEntry] = (
            OrderedDict()
        )

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(
        self,
        bead_id: str,
        project_ref: str | None = None,
        *,
        context_key: str | None = None,
    ) -> BeadMentionEntry | None:
        """Return the entry for *bead_id*, refreshing its LRU position."""
        key = _mention_index_key(bead_id, project_ref, context_key)
        try:
            entry = self._entries.pop(key)
        except KeyError:
            return None
        self._entries[key] = entry
        return entry

    def peek(
        self,
        bead_id: str,
        project_ref: str | None = None,
        *,
        context_key: str | None = None,
    ) -> BeadMentionEntry | None:
        """Return the entry for *bead_id* without touching LRU order."""
        return self._entries.get(_mention_index_key(bead_id, project_ref, context_key))

    def store(
        self,
        bead_id: str,
        entry: BeadMentionEntry,
        project_ref: str | None = None,
        *,
        context_key: str | None = None,
    ) -> bool:
        """Store *entry* under *bead_id*; return whether anything changed.

        Evicts least-recently-used entries past the bound.
        """
        key = _mention_index_key(bead_id, project_ref, context_key)
        try:
            previous = self._entries.pop(key)
        except KeyError:
            previous = None
        self._entries[key] = entry
        while len(self._entries) > self._bound:
            self._entries.popitem(last=False)
        return previous != entry

    def entries_for_store(
        self, store_key: str
    ) -> tuple[tuple[BeadMentionRequest, BeadMentionEntry], ...]:
        """Return every scoped target resolved against *store_key*."""
        return tuple(
            (BeadMentionRequest(bead_id, context_key=project_ref), entry)
            for (bead_id, project_ref), entry in self._entries.items()
            if entry.store_key == store_key
        )

    def clear(self) -> None:
        """Drop every entry (config/project sources changed)."""
        self._entries.clear()


@dataclass(frozen=True)
class BeadMentionRequest:
    """One mention and the project context used to disambiguate its owner."""

    bead_id: str
    project_ref: str | None = None
    context_key: str | None = None

    def __post_init__(self) -> None:
        if self.project_ref is not None:
            normalized = self.project_ref.strip().casefold() or None
            object.__setattr__(self, "project_ref", normalized)
        if self.context_key is not None:
            normalized_context = self.context_key.strip().casefold() or None
            object.__setattr__(self, "context_key", normalized_context)


def _mention_index_key(
    bead_id: str,
    project_ref: str | None,
    context_key: str | None = None,
) -> tuple[str, str | None]:
    scope = context_key if context_key is not None else project_ref
    context = scope.strip().casefold() if scope else None
    return bead_id, context or None


@dataclass(frozen=True)
class BeadMentionResolutionPlan:
    """UI-thread snapshot routed by :func:`resolve_bead_mention_updates`."""

    directory: BeadStoreDirectory
    requests: tuple[BeadMentionRequest, ...]
    known: tuple[tuple[BeadMentionRequest, BeadMentionEntry], ...]


@dataclass(frozen=True)
class _BeadMentionStorePlan:
    """One store slice of a mention-resolution run (worker-local snapshot).

    ``candidates`` are scoped mention requests routed to ``store``. ``known``
    is the matching index slice at plan time.
    """

    store: BeadStoreRef
    candidates: tuple[BeadMentionRequest, ...]
    known: tuple[tuple[BeadMentionRequest, BeadMentionEntry], ...]


def resolve_bead_mention_updates(
    plan: BeadMentionResolutionPlan,
) -> list[tuple[BeadMentionRequest, BeadMentionEntry]]:
    """Resolve one mention-resolution plan (off-thread entry point).

    Route each request using the Rust-backed target router, then group the
    requests by their actual owner. Re-query statuses only for unknown IDs
    or entries whose fingerprint changed. Ambiguous, missing and unavailable
    requests are explicitly marked unstyled so an old owner cannot leak a
    status into a different prompt context.
    """
    import logging

    from sase.core.bead_read_facade import statuses_for_ids

    log = logging.getLogger(__name__)
    updates: list[tuple[BeadMentionRequest, BeadMentionEntry]] = []
    known_map = dict(plan.known)
    groups: dict[str, tuple[BeadStoreRef, list[BeadMentionRequest]]] = {}
    for request in plan.requests:
        try:
            route = route_bead_mention(
                request.bead_id,
                plan.directory,
                project_ref=request.project_ref,
            )
        except Exception:
            log.debug(
                "Bead mention routing failed for %r", request.bead_id, exc_info=True
            )
            updates.append((request, BeadMentionEntry(None, "", None)))
            continue
        if not isinstance(route, BeadRouteFound):
            updates.append((request, BeadMentionEntry(None, "", None)))
            continue
        store = route.store
        store_key = str(store.beads_dir)
        if store_key not in groups:
            groups[store_key] = (store, [])
        if request not in groups[store_key][1]:
            groups[store_key][1].append(request)

    store_plans = tuple(
        _BeadMentionStorePlan(
            store=store,
            candidates=tuple(requests),
            known=tuple(
                (request, known_map[request])
                for request in requests
                if request in known_map
            ),
        )
        for store, requests in groups.values()
    )
    for group in store_plans:
        store = group.store
        store_key = str(store.beads_dir)
        token = _store_fingerprint_token(store.beads_dir)
        known_map = dict(group.known)
        needed = [
            request
            for request in group.candidates
            if _mention_entry_is_stale(known_map.get(request), store_key, token)
        ]
        if not needed:
            continue
        needed_ids = sorted({request.bead_id for request in needed})
        try:
            statuses = statuses_for_ids(store.beads_dir, needed_ids)
        except Exception:
            log.debug(
                "Bead mention status query failed for %r", store_key, exc_info=True
            )
            updates.extend(
                (request, BeadMentionEntry(None, store_key, None)) for request in needed
            )
            continue
        for request in needed:
            updates.append(
                (
                    request,
                    BeadMentionEntry(
                        status=statuses.get(request.bead_id),
                        store_key=store_key,
                        fingerprint_token=token,
                    ),
                )
            )
    return updates


def _mention_entry_is_stale(
    entry: BeadMentionEntry | None,
    store_key: str,
    token: str | None,
) -> bool:
    """Return whether *entry* needs a re-query against (*store_key*, *token*)."""
    if entry is None:
        return True
    return (
        token is None
        or entry.store_key != store_key
        or entry.fingerprint_token != token
    )


def _store_fingerprint_token(beads_dir: Path | str) -> str | None:
    """Return the stat-only fingerprint token for *beads_dir*, if available.

    Fail-open: ``None`` when the core predates the binding or the store
    cannot be fingerprinted. Call off-thread only.
    """
    from sase.core.bead_read_facade import store_fingerprint

    try:
        fingerprint = store_fingerprint(beads_dir)
    except Exception:
        return None
    if fingerprint is None:
        return None
    return fingerprint.token


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
    "BEAD_MENTION_INDEX_BOUND",
    "BeadMentionEntry",
    "BeadMentionIndex",
    "BeadMentionRequest",
    "BeadMentionResolutionPlan",
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
    "resolve_bead_mention_updates",
    "route_bead_mention",
]

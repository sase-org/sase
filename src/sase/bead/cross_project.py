"""Read-only cross-project bead-store discovery helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.bead_target_routing_facade import (
    BeadTargetRoute,
    BeadTargetStoreDescriptor,
    error_bead_target_route,
    resolved_bead_target_route,
)
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name

_BEAD_ID_RE = re.compile(r"^[^\s.]+-[0-9a-z]+(?:\.\d+)*$")


@dataclass(frozen=True)
class BeadStoreOrigin:
    """One enabled project's canonical, read-only bead store."""

    project_key: str
    project_label: str
    primary_workspace: Path
    beads_dir: Path | None


@dataclass(frozen=True)
class BeadStoreSnapshot:
    """One enabled project's canonical bead-store snapshot for Rust routing."""

    origin: BeadStoreOrigin
    store_key: str
    issue_ids: frozenset[str]
    issue_prefix: str | None
    project_refs: frozenset[str]
    unavailable_reason: str | None = None

    def descriptor(self) -> BeadTargetStoreDescriptor:
        """Return the Rust routing descriptor for this discovered store."""

        return BeadTargetStoreDescriptor(
            store_key=self.store_key,
            project_key=self.origin.project_key,
            project_label=self.origin.project_label,
            primary_workspace=self.origin.primary_workspace,
            beads_dir=self.origin.beads_dir,
            issue_prefix=self.issue_prefix,
            project_refs=tuple(sorted(self.project_refs)),
            issue_ids=tuple(sorted(self.issue_ids)),
            unavailable_reason=self.unavailable_reason,
        )


class AmbiguousBeadProjectError(ValueError):
    """Two or more enabled projects claim one bead prefix or project ref."""

    def __init__(
        self,
        ref: str,
        candidates: Sequence[BeadStoreOrigin],
        *,
        subject: str,
    ) -> None:
        self.ref = ref
        self.candidates = tuple(candidates)
        labels = ", ".join(_candidate_label(candidate) for candidate in candidates)
        super().__init__(
            f"ambiguous {subject} {ref!r} matched multiple enabled projects: "
            f"{labels}; use -P/--project"
        )


def bead_id_prefix(bead_id: str) -> str | None:
    """Return the prefix for a full bead ID, or ``None`` for shorthand/malformed."""
    if not _BEAD_ID_RE.fullmatch(bead_id):
        return None
    top_level = bead_id.split(".", maxsplit=1)[0]
    prefix, separator, _counter = top_level.rpartition("-")
    if not separator or not prefix:
        return None
    return prefix


def enabled_project_store_snapshots() -> tuple[BeadStoreSnapshot, ...]:
    """Return read-only snapshots for enabled projects' canonical bead stores."""
    return tuple(_snapshot_for_record(record) for record in _enabled_project_records())


def route_full_id_with_snapshots(
    bead_id: str,
    snapshots: Sequence[BeadStoreSnapshot],
    *,
    local_store: BeadTargetStoreDescriptor | None = None,
) -> BeadTargetRoute | None:
    """Route one full bead ID using already-discovered project snapshots."""
    route = route_bead_target_via_probe(
        bead_id,
        local_store=local_store,
        candidates=[snapshot.descriptor() for snapshot in snapshots],
    )
    return route if route.requested_id == bead_id else None


def probe_bead_target_owner(
    beads_dir: Path | str,
    target: str,
) -> tuple[str, str | None]:
    """Probe whether a bead store could own *target* without reading it.

    Returns the ``(status, stem)`` pair: ``hit`` when a lineage stem file
    exists (including tombstoned and relocated stems), ``miss`` when no stem
    matches, and ``unknown`` for stores without an event layout. Only
    filesystem stats, never a store replay.
    """
    from sase.core.rust import require_rust_binding

    binding = require_rust_binding("bead_probe_target_owner")
    outcome = binding(str(beads_dir), target)
    if not isinstance(outcome, dict):
        return "unknown", None
    status = str(outcome.get("status") or "unknown")
    stem = outcome.get("stem")
    return status, (str(stem) if stem else None)


def route_bead_target_via_probe(
    target: str,
    *,
    local_store: BeadTargetStoreDescriptor | None = None,
    candidates: Sequence[BeadTargetStoreDescriptor] = (),
) -> BeadTargetRoute:
    """Route one bead target to its owning store without any store read.

    Shorthand targets are local by definition and never consult foreign
    stores. Full IDs probe lineage stem files: a root ID owns
    ``events/streams/<id>.jsonl`` and a phase lives in its parent plan's
    stream, so dotted IDs walk their lineage prefixes. Tombstoned and
    relocated stems still route to their store because the file exists.

    ``resolved_id`` carries the requested ID forward (canonical for full
    IDs, raw for shorthand): the operation's own locked load stays the
    authority for existence and ambiguity, so routing error text matches
    the ID router it replaces.

    An explicitly provided ID list on a descriptor is authoritative when
    present: production descriptors leave it empty (nothing is ever listed
    for routing), but callers with a pre-resolved registry may still pass
    one. The filesystem probe decides everywhere else.
    """
    if bead_id_prefix(target) is None:
        return _route_shorthand_target(target, local_store)
    return _route_full_id_target(target, local_store, candidates)


def _route_shorthand_target(
    target: str,
    local_store: BeadTargetStoreDescriptor | None,
) -> BeadTargetRoute:
    if local_store is None:
        return error_bead_target_route(
            target,
            kind="unavailable",
            message="no local bead store is available",
        )
    if local_store.unavailable_reason is not None:
        return error_bead_target_route(
            target,
            kind="unavailable",
            message=_unavailable_message(target, [local_store]),
            candidates=[local_store],
        )
    if _probe_status(local_store, target) == "unknown":
        legacy = _legacy_match_route(
            local_store, _legacy_issue_ids(local_store), target
        )
        if legacy is not None:
            return legacy
    return resolved_bead_target_route(target, target, local_store)


def _route_full_id_target(
    target: str,
    local_store: BeadTargetStoreDescriptor | None,
    candidates: Sequence[BeadTargetStoreDescriptor],
) -> BeadTargetRoute:
    local_usable = (
        local_store is not None
        and local_store.unavailable_reason is None
        and local_store.beads_dir is not None
    )
    if local_usable:
        assert local_store is not None
        if target in local_store.issue_ids:
            return resolved_bead_target_route(target, target, local_store)
        status = _probe_status(local_store, target)
        if status == "hit":
            return resolved_bead_target_route(target, target, local_store)
        if status == "unknown":
            try:
                legacy_ids = _legacy_issue_ids(local_store)
            except (OSError, RuntimeError, ValueError):
                local_usable = False
            else:
                legacy = _legacy_match_route(local_store, legacy_ids, target)
                if legacy is not None:
                    return legacy
    hits: list[BeadTargetStoreDescriptor] = []
    relevant_unavailable: list[BeadTargetStoreDescriptor] = []
    for candidate in candidates:
        if candidate.unavailable_reason is not None or candidate.beads_dir is None:
            if _prefix_matches_store(target, candidate):
                relevant_unavailable.append(candidate)
            continue
        if target in candidate.issue_ids:
            hits.append(candidate)
            continue
        status = _probe_status(candidate, target)
        if status == "hit":
            hits.append(candidate)
        elif status == "unknown":
            try:
                legacy_ids = _legacy_issue_ids(candidate)
            except (OSError, RuntimeError, ValueError):
                if _prefix_matches_store(target, candidate):
                    relevant_unavailable.append(candidate)
                continue
            if target in legacy_ids:
                hits.append(candidate)
    if len(hits) > 1:
        return error_bead_target_route(
            target,
            kind="ambiguous",
            message=_ambiguity_message(target, hits),
            candidates=hits,
        )
    if hits:
        return resolved_bead_target_route(target, target, hits[0])
    if relevant_unavailable:
        return error_bead_target_route(
            target,
            kind="unavailable",
            message=_unavailable_message(target, relevant_unavailable),
            candidates=relevant_unavailable,
        )
    if local_usable:
        assert local_store is not None
        return resolved_bead_target_route(target, target, local_store)
    return error_bead_target_route(
        target,
        kind="not_found",
        message=f"issue not found: {target}",
    )


def _probe_status(store: BeadTargetStoreDescriptor, target: str) -> str:
    beads_dir = store.beads_dir
    if beads_dir is None:
        return "unknown"
    status, _stem = probe_bead_target_owner(beads_dir, target)
    return status


def _legacy_issue_ids(store: BeadTargetStoreDescriptor) -> frozenset[str]:
    """List one legacy (non-event-layout) store's IDs for routing only.

    Modern stores never reach this path: their probe reports hit or miss.
    """
    beads_dir = store.beads_dir
    if beads_dir is None:
        raise OSError(f"bead store {store.store_key} is not materialized")
    from sase.bead.store_locator import open_bead_project_for_beads_dir

    with open_bead_project_for_beads_dir(Path(beads_dir)) as project:
        return frozenset(issue.id for issue in project.list_issues())


def _legacy_match_route(
    store: BeadTargetStoreDescriptor,
    issue_ids: frozenset[str],
    target: str,
) -> BeadTargetRoute | None:
    """Match *target* against a legacy store's ID list, or ``None`` on miss."""
    if bead_id_prefix(target) is None:
        matches = sorted(
            {
                issue_id
                for issue_id in issue_ids
                if issue_id.rsplit("-", 1)[-1] == target
            }
        )
        if len(matches) > 1:
            return error_bead_target_route(
                target,
                kind="ambiguous",
                message=(
                    f"ambiguous bead ID shorthand {target!r}: {', '.join(matches)}"
                ),
                candidates=[store],
            )
        if matches:
            return resolved_bead_target_route(target, matches[0], store)
        return None
    if target in issue_ids:
        return resolved_bead_target_route(target, target, store)
    return None


def _prefix_matches_store(
    target: str,
    store: BeadTargetStoreDescriptor,
) -> bool:
    """Mirror the ID router's unavailable-store relevance check."""
    prefix = bead_id_prefix(target)
    if prefix is None:
        return False
    return store.issue_prefix == prefix or prefix in store.project_refs


def _store_route_label(store: BeadTargetStoreDescriptor) -> str:
    return store.project_label or store.project_key or store.store_key


def _store_route_display_label(store: BeadTargetStoreDescriptor) -> str:
    label = _store_route_label(store)
    if store.project_key and store.project_key != label:
        return f"{label} ({store.project_key})"
    return label


def _unavailable_message(
    target: str,
    stores: Sequence[BeadTargetStoreDescriptor],
) -> str:
    """Mirror the ID router's unavailable-store message."""
    if len(stores) == 1:
        return (
            f"project '{_store_route_label(stores[0])}' owns '{target}', "
            "but its bead store is not materialized on this machine"
        )
    if not stores:
        return f"bead store for '{target}' is unavailable"
    labels = ", ".join(_store_route_label(store) for store in stores)
    return f"bead stores that may own '{target}' are unavailable: {labels}"


def _ambiguity_message(
    target: str,
    stores: Sequence[BeadTargetStoreDescriptor],
) -> str:
    """Mirror the ID router's multi-store ambiguity message."""
    labels = ", ".join(_store_route_display_label(store) for store in stores)
    return (
        f"ambiguous bead ID '{target}' matched multiple enabled project "
        f"stores: {labels}; use -P/--project"
    )


def origin_for_project_ref(project_ref: str) -> BeadStoreOrigin | None:
    """Resolve an explicit project key, display label, or alias."""
    folded = project_ref.casefold()
    matches = [
        record
        for record in _enabled_project_records()
        if folded in _casefolded_project_refs(record)
    ]
    if len(matches) > 1:
        raise AmbiguousBeadProjectError(
            project_ref,
            [_origin_for_record(record, beads_dir=None) for record in matches],
            subject="project",
        )
    if not matches:
        return None
    record = matches[0]
    return _origin_for_record(
        record,
        beads_dir=_canonical_beads_dir(record.project_name),
    )


def enabled_project_ref_prefixes() -> tuple[str, ...]:
    """Return every enabled project's refs as bead-ID prefixes.

    Project refs (name, effective name, aliases) double as the default
    bead-ID prefixes the routing layer accepts, so pager bare-token
    recognition uses the same set. Reads no bead store.
    """
    return tuple(
        sorted(set().union(*(_project_refs(r) for r in _enabled_project_records())))
    )


def _enabled_project_records() -> tuple[ProjectRecordWire, ...]:
    return tuple(
        record
        for record in list_project_records(
            sase_projects_dir(),
            "enabled",
            include_home=False,
            projects_only=True,
        )
        if record.is_project
    )


def _snapshot_for_record(record: ProjectRecordWire) -> BeadStoreSnapshot:
    # One-replay routing: snapshots never read the store. Ownership is
    # decided by the filesystem probe (prefix plus lineage stems), and the
    # mutation's locked resolution stays the authority for existence.
    beads_dir = _canonical_beads_dir(record.project_name)
    origin = _origin_for_record(record, beads_dir=beads_dir)
    issue_prefix = _stored_issue_prefix(beads_dir) if beads_dir is not None else None
    unavailable_reason: str | None = None
    if beads_dir is None:
        unavailable_reason = "not materialized"
    return BeadStoreSnapshot(
        origin=origin,
        store_key=_store_key_for_origin(origin),
        issue_ids=frozenset(),
        issue_prefix=issue_prefix,
        project_refs=frozenset(_project_refs(record)),
        unavailable_reason=unavailable_reason,
    )


def _project_refs(record: ProjectRecordWire) -> set[str]:
    return {record.project_name, effective_project_name(record), *record.aliases}


def _casefolded_project_refs(record: ProjectRecordWire) -> set[str]:
    return {ref.casefold() for ref in _project_refs(record)}


def _origin_for_record(
    record: ProjectRecordWire,
    *,
    beads_dir: Path | None,
) -> BeadStoreOrigin:
    return BeadStoreOrigin(
        project_key=record.project_name,
        project_label=effective_project_name(record),
        primary_workspace=_primary_workspace_for(record, beads_dir=beads_dir),
        beads_dir=beads_dir,
    )


def _primary_workspace_for(
    record: ProjectRecordWire,
    *,
    beads_dir: Path | None,
) -> Path:
    if record.workspace_dir:
        return Path(record.workspace_dir).expanduser()
    if beads_dir is not None:
        return beads_dir.parent
    return Path(record.project_dir).expanduser()


def _canonical_beads_dir(project_key: str) -> Path | None:
    from sase.bead.store_locator import canonical_beads_dir_for_project

    return canonical_beads_dir_for_project(project_key)


def _stored_issue_prefix(beads_dir: Path) -> str | None:
    try:
        payload = json.loads((beads_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    prefix = payload.get("issue_prefix")
    return prefix if isinstance(prefix, str) and prefix else None


def _candidate_label(origin: BeadStoreOrigin) -> str:
    if origin.project_label == origin.project_key:
        return origin.project_key
    return f"{origin.project_label} ({origin.project_key})"


def _store_key_for_origin(origin: BeadStoreOrigin) -> str:
    if origin.beads_dir is None:
        return f"project:{origin.project_key}"
    return str(origin.beads_dir.expanduser().resolve(strict=False))


__all__ = [
    "AmbiguousBeadProjectError",
    "BeadStoreOrigin",
    "BeadStoreSnapshot",
    "bead_id_prefix",
    "enabled_project_ref_prefixes",
    "enabled_project_store_snapshots",
    "origin_for_project_ref",
    "probe_bead_target_owner",
    "route_bead_target_via_probe",
    "route_full_id_with_snapshots",
]

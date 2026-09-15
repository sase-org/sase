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
    route_bead_targets,
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
    outcome = route_bead_targets(
        [bead_id],
        local_store=local_store,
        candidate_stores=[snapshot.descriptor() for snapshot in snapshots],
    )
    return _single_route(outcome.routes, bead_id)


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
    beads_dir = _canonical_beads_dir(record.project_name)
    origin = _origin_for_record(record, beads_dir=beads_dir)
    issue_prefix = _stored_issue_prefix(beads_dir) if beads_dir is not None else None
    issue_ids: frozenset[str] = frozenset()
    unavailable_reason: str | None = None
    if beads_dir is None:
        unavailable_reason = "not materialized"
    else:
        try:
            from sase.bead.store_locator import open_bead_project_for_beads_dir

            with open_bead_project_for_beads_dir(beads_dir) as project:
                issue_ids = frozenset(issue.id for issue in project.list_issues())
        except (OSError, RuntimeError, ValueError) as exc:
            unavailable_reason = str(exc) or "not readable"
    return BeadStoreSnapshot(
        origin=origin,
        store_key=_store_key_for_origin(origin),
        issue_ids=issue_ids,
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


def _single_route(
    routes: Sequence[BeadTargetRoute],
    bead_id: str,
) -> BeadTargetRoute | None:
    for route in routes:
        if route.requested_id == bead_id:
            return route
    return None


__all__ = [
    "AmbiguousBeadProjectError",
    "BeadStoreOrigin",
    "BeadStoreSnapshot",
    "bead_id_prefix",
    "enabled_project_store_snapshots",
    "origin_for_project_ref",
    "route_full_id_with_snapshots",
]

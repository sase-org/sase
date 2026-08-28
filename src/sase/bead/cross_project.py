"""Read-only cross-project bead-store routing helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import sase_projects_dir
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


def _bead_id_prefix(bead_id: str) -> str | None:
    """Return the prefix for a full bead ID, or ``None`` for shorthand/malformed."""
    if not _BEAD_ID_RE.fullmatch(bead_id):
        return None
    top_level = bead_id.split(".", maxsplit=1)[0]
    prefix, separator, _counter = top_level.rpartition("-")
    if not separator or not prefix:
        return None
    return prefix


def origin_for_bead_id(bead_id: str) -> BeadStoreOrigin | None:
    """Resolve a full bead ID to the enabled project that owns its prefix."""
    prefix = _bead_id_prefix(bead_id)
    if prefix is None:
        return None

    records = _enabled_project_records()
    registry_matches = _records_matching_prefix(records, prefix)
    if len(registry_matches) > 1:
        raise AmbiguousBeadProjectError(
            prefix,
            [_origin_for_record(record, beads_dir=None) for record in registry_matches],
            subject="bead prefix",
        )
    if registry_matches:
        record = registry_matches[0]
        beads_dir = _canonical_beads_dir(record.project_name)
        origin = _origin_for_record(record, beads_dir=beads_dir)
        if beads_dir is None:
            return origin
        if _stored_issue_prefix(beads_dir) == prefix:
            return origin

    store_matches = _records_matching_stored_prefix(records, prefix)
    if len(store_matches) > 1:
        raise AmbiguousBeadProjectError(
            prefix,
            list(store_matches),
            subject="bead prefix",
        )
    return store_matches[0] if store_matches else None


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


def _records_matching_prefix(
    records: Iterable[ProjectRecordWire],
    prefix: str,
) -> list[ProjectRecordWire]:
    matches: list[ProjectRecordWire] = []
    seen: set[str] = set()
    for record in records:
        if prefix in _project_refs(record) and record.project_name not in seen:
            matches.append(record)
            seen.add(record.project_name)
    return matches


def _records_matching_stored_prefix(
    records: Iterable[ProjectRecordWire],
    prefix: str,
) -> list[BeadStoreOrigin]:
    matches: list[BeadStoreOrigin] = []
    seen: set[str] = set()
    for record in records:
        if record.project_name in seen:
            continue
        beads_dir = _canonical_beads_dir(record.project_name)
        if beads_dir is None:
            continue
        if _stored_issue_prefix(beads_dir) != prefix:
            continue
        matches.append(_origin_for_record(record, beads_dir=beads_dir))
        seen.add(record.project_name)
    return matches


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


__all__ = [
    "AmbiguousBeadProjectError",
    "BeadStoreOrigin",
    "origin_for_bead_id",
    "origin_for_project_ref",
]

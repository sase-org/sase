"""Project alias record filtering, validation, and name allocation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name
from sase.core.project_lifecycle_wire import ProjectRecordWire

logger = logging.getLogger(__name__)

ListProjectRecords = Callable[..., list[ProjectRecordWire]]


@dataclass(frozen=True)
class ProjectRefConflict:
    """A PROJECT_NAME or alias that collides with another project's refs.

    ``claimant`` declared *ref* as ``PROJECT_NAME`` or an alias.
    ``occupant`` is the project whose directory key already is that ref,
    or the earlier claimant of the same alias.
    """

    ref: str
    kind: str
    claimant: str
    occupant: str
    claimant_workspace_dir: str | None = None
    occupant_workspace_dir: str | None = None


def filtered_project_records(
    projects_root: Path | str,
    *,
    list_project_records: ListProjectRecords,
) -> list[ProjectRecordWire]:
    """Return user-managed records from an existing projects directory."""
    root = Path(projects_root)
    if not root.is_dir():
        return []
    try:
        records = list_project_records(root, "all", include_home=False)
    except (ImportError, AttributeError):
        return []
    return _non_system_project_records(records)


def normalize_project_aliases(aliases: Iterable[str]) -> list[str]:
    """Return trimmed, deduplicated project aliases in stable order."""
    return sorted({alias.strip() for alias in aliases if alias.strip()})


def normalize_project_name(name: str | None) -> str | None:
    """Return a trimmed display name, or ``None`` when blank/unset."""
    if name is None:
        return None
    value = name.strip()
    return value or None


def _non_system_project_records(
    records: Sequence[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    """Return records that may participate in project ref resolution."""
    return [
        record
        for record in records
        if record.is_project
        and record.project_name != "home"
        and not record.system_managed
    ]


def _project_record_has_spec(record: ProjectRecordWire) -> bool:
    return Path(record.project_file).is_file() or record.archive_file is not None


def _spec_backed_project_records(
    records: Sequence[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    return [
        record
        for record in _non_system_project_records(records)
        if _project_record_has_spec(record)
    ]


#: Folded ref reserved for the system ``home`` project. No other project
#: may claim it as a directory key, ``PROJECT_NAME``, or alias.
_RESERVED_HOME_FOLD = "home"


def _fold_project_ref(ref: str) -> str:
    """Return the case-insensitive comparison form of a project ref."""
    return ref.casefold()


def project_alias_map_from_records(
    records: Sequence[ProjectRecordWire],
    *,
    overrides: Mapping[str, Sequence[str]] | None = None,
    display_name_overrides: Mapping[str, str | None] | None = None,
    strict: bool = True,
) -> dict[str, str]:
    """Build ``ref -> canonical project`` from *records*.

    Refs compare case-insensitively: ``Foo`` and ``foo`` identify the same
    ref. Strict mutation paths reject conflicting refs. Read paths instead
    drop conflicts deterministically so stale data cannot prevent project
    startup.
    """
    spec_backed_records = _spec_backed_project_records(records)
    folded_project_names: dict[str, str] = {}
    for record in spec_backed_records:
        folded_project_names.setdefault(
            _fold_project_ref(record.project_name), record.project_name
        )
    alias_map: dict[str, str] = {}
    folded_refs: dict[str, str] = {}
    ref_kinds: dict[tuple[str, str], str] = {}

    def _add_ref(ref: str, project_name: str, kind: str) -> None:
        if not is_valid_sase_project_name(ref):
            raise ValueError(f"invalid {kind} {ref!r} for project {project_name!r}")
        fold = _fold_project_ref(ref)
        own_fold = _fold_project_ref(project_name)
        if fold == _RESERVED_HOME_FOLD:
            raise ValueError(
                f"project reference {ref!r} for project {project_name!r} "
                "is reserved for the system home project"
            )
        if fold == own_fold:
            if kind == "PROJECT_NAME":
                return
            raise ValueError(
                f"project alias {ref!r} cannot equal project {project_name!r}"
            )
        if fold in folded_project_names:
            if kind == "PROJECT_NAME":
                raise ValueError(
                    f"PROJECT_NAME {ref!r} for project {project_name!r} "
                    "conflicts with a real project name"
                )
            raise ValueError(
                f"project alias {ref!r} for project {project_name!r} "
                "conflicts with a real project name"
            )
        existing = folded_refs.get(fold)
        if existing is not None:
            existing_owner = alias_map[existing]
            if existing_owner != project_name:
                raise ValueError(
                    f"project reference {ref!r} is assigned to both "
                    f"{existing_owner!r} and {project_name!r}"
                )
            existing_kind = ref_kinds.get((project_name, fold), "project reference")
            if existing_kind != kind:
                raise ValueError(
                    f"{kind} {ref!r} for project {project_name!r} conflicts "
                    f"with {existing_kind}"
                )
            return
        alias_map[ref] = project_name
        folded_refs[fold] = ref
        ref_kinds[(project_name, fold)] = kind

    dropped_folds: set[str] = set()

    def add_ref(ref: str, project_name: str, kind: str) -> None:
        fold = _fold_project_ref(ref)
        if not strict and fold in dropped_folds:
            logger.warning(
                "Ignoring conflicting %s %r for project %r",
                kind,
                ref,
                project_name,
            )
            return
        try:
            _add_ref(ref, project_name, kind)
        except ValueError:
            if strict:
                raise
            existing = folded_refs.get(fold)
            if existing is not None and alias_map.get(existing) != project_name:
                del alias_map[existing]
                del folded_refs[fold]
                dropped_folds.add(fold)
            else:
                dropped_folds.add(fold)
            logger.warning(
                "Ignoring conflicting %s %r for project %r",
                kind,
                ref,
                project_name,
            )

    for record in spec_backed_records:
        display_name = (
            normalize_project_name(display_name_overrides[record.project_name])
            if display_name_overrides is not None
            and record.project_name in display_name_overrides
            else record.display_name
        )
        if display_name is not None:
            add_ref(display_name, record.project_name, "PROJECT_NAME")

        aliases = (
            overrides[record.project_name]
            if overrides is not None and record.project_name in overrides
            else record.aliases
        )
        for alias in normalize_project_aliases(aliases):
            add_ref(alias, record.project_name, "project alias")

    return alias_map


def project_ref_conflicts_from_records(
    records: Sequence[ProjectRecordWire],
) -> tuple[ProjectRefConflict, ...]:
    """Return dropped/conflicting refs that alias-map construction would ignore.

    Refs compare case-insensitively. Each conflict names the claimant (the
    project that declared the ref as ``PROJECT_NAME`` or alias) and the
    occupant (the project whose directory key already is that ref, the
    earlier claimant of the same alias, or ``home`` for the reserved ref).
    """
    spec_backed = _spec_backed_project_records(records)
    by_name = {record.project_name: record for record in spec_backed}
    folded_project_names: dict[str, str] = {}
    for record in spec_backed:
        folded_project_names.setdefault(
            _fold_project_ref(record.project_name), record.project_name
        )
    claimed: dict[str, str] = {}
    conflicts: list[ProjectRefConflict] = []

    def _conflict(
        ref: str, kind: str, claimant: str, occupant: str
    ) -> ProjectRefConflict:
        claimant_record = by_name.get(claimant)
        occupant_record = by_name.get(occupant)
        return ProjectRefConflict(
            ref=ref,
            kind=kind,
            claimant=claimant,
            occupant=occupant,
            claimant_workspace_dir=(
                claimant_record.workspace_dir if claimant_record is not None else None
            ),
            occupant_workspace_dir=(
                occupant_record.workspace_dir if occupant_record is not None else None
            ),
        )

    for record in spec_backed:
        own_fold = _fold_project_ref(record.project_name)
        claims: list[tuple[str, str]] = []
        display_name = normalize_project_name(record.display_name)
        if display_name is not None and (_fold_project_ref(display_name) != own_fold):
            claims.append((display_name, "PROJECT_NAME"))
        for alias in normalize_project_aliases(record.aliases):
            if _fold_project_ref(alias) != own_fold:
                claims.append((alias, "project alias"))

        for ref, kind in claims:
            if not is_valid_sase_project_name(ref):
                continue
            fold = _fold_project_ref(ref)
            if fold == _RESERVED_HOME_FOLD:
                conflicts.append(_conflict(ref, kind, record.project_name, "home"))
                continue
            occupant = folded_project_names.get(fold)
            if occupant is not None and occupant != record.project_name:
                conflicts.append(_conflict(ref, kind, record.project_name, occupant))
                continue
            existing = claimed.get(fold)
            if existing is not None and existing != record.project_name:
                conflicts.append(_conflict(ref, kind, record.project_name, existing))
                continue
            claimed.setdefault(fold, record.project_name)

    return tuple(conflicts)


def validate_project_aliases(
    project_name: str,
    aliases: Iterable[str],
    records: Sequence[ProjectRecordWire],
) -> list[str]:
    """Validate proposed aliases for one project against project records."""
    normalized = normalize_project_aliases(aliases)
    project_alias_map_from_records(records, overrides={project_name: normalized})
    return normalized


def validate_project_name(
    project_name: str,
    name: str | None,
    records: Sequence[ProjectRecordWire],
) -> str | None:
    """Validate a proposed ``PROJECT_NAME`` for one project."""
    normalized = normalize_project_name(name)
    if normalized is not None and not is_valid_sase_project_name(normalized):
        raise ValueError(f"invalid project name: {name!r}")
    project_alias_map_from_records(
        records,
        display_name_overrides={project_name: normalized},
    )
    return normalized


def _occupied_project_refs(
    records: Sequence[ProjectRecordWire],
    *,
    project_name: str | None = None,
    include_current_aliases: bool = True,
    include_current_display_name: bool = True,
) -> set[str]:
    occupied = {
        _fold_project_ref(record.project_name)
        for record in _non_system_project_records(records)
    }
    occupied.add(_RESERVED_HOME_FOLD)
    for record in _non_system_project_records(records):
        is_current = project_name is not None and record.project_name == project_name
        if not is_current or include_current_aliases:
            occupied.update(
                _fold_project_ref(alias)
                for alias in normalize_project_aliases(record.aliases)
            )
        if not is_current or include_current_display_name:
            if record.display_name:
                occupied.add(_fold_project_ref(record.display_name))
    return occupied


def allocate_project_name(
    desired_base_name: str,
    records: Sequence[ProjectRecordWire],
    *,
    project_name: str | None = None,
) -> str:
    """Return the first available logical project name for *desired_base_name*.

    Availability compares case-insensitively, and ``home`` is always
    reserved for the system project.
    """
    base = desired_base_name.strip()
    if not is_valid_sase_project_name(base):
        raise ValueError(f"invalid project name: {desired_base_name!r}")

    occupied = _occupied_project_refs(
        records,
        project_name=project_name,
        include_current_aliases=True,
        include_current_display_name=False,
    )
    candidate = base
    suffix = 1
    while _fold_project_ref(candidate) in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate

"""Project alias record filtering, validation, and name allocation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name
from sase.core.project_lifecycle_wire import ProjectRecordWire

logger = logging.getLogger(__name__)

ListProjectRecords = Callable[..., list[ProjectRecordWire]]


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
        if record.project_name != "home" and not record.system_managed
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


def project_alias_map_from_records(
    records: Sequence[ProjectRecordWire],
    *,
    overrides: Mapping[str, Sequence[str]] | None = None,
    display_name_overrides: Mapping[str, str | None] | None = None,
    strict: bool = True,
) -> dict[str, str]:
    """Build ``ref -> canonical project`` from *records*.

    Strict mutation paths reject conflicting refs. Read paths instead drop
    conflicts deterministically so stale data cannot prevent project startup.
    """
    spec_backed_records = _spec_backed_project_records(records)
    project_names = {record.project_name for record in spec_backed_records}
    alias_map: dict[str, str] = {}
    ref_kinds: dict[tuple[str, str], str] = {}

    def _add_ref(ref: str, project_name: str, kind: str) -> None:
        if not is_valid_sase_project_name(ref):
            raise ValueError(f"invalid {kind} {ref!r} for project {project_name!r}")
        if ref == project_name:
            if kind == "PROJECT_NAME":
                return
            raise ValueError(
                f"project alias {ref!r} cannot equal project {project_name!r}"
            )
        if ref in project_names:
            if kind == "PROJECT_NAME":
                raise ValueError(
                    f"PROJECT_NAME {ref!r} for project {project_name!r} "
                    "conflicts with a real project name"
                )
            raise ValueError(
                f"project alias {ref!r} for project {project_name!r} "
                "conflicts with a real project name"
            )
        existing = alias_map.get(ref)
        if existing is not None and existing != project_name:
            raise ValueError(
                f"project reference {ref!r} is assigned to both "
                f"{existing!r} and {project_name!r}"
            )
        if existing == project_name:
            existing_kind = ref_kinds.get((project_name, ref), "project reference")
            if existing_kind != kind:
                raise ValueError(
                    f"{kind} {ref!r} for project {project_name!r} conflicts "
                    f"with {existing_kind}"
                )
            return
        alias_map[ref] = project_name
        ref_kinds[(project_name, ref)] = kind

    dropped_refs: set[str] = set()

    def add_ref(ref: str, project_name: str, kind: str) -> None:
        if not strict and ref in dropped_refs:
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
            existing = alias_map.get(ref)
            if existing is not None and existing != project_name:
                del alias_map[ref]
                dropped_refs.add(ref)
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
    occupied = {record.project_name for record in _non_system_project_records(records)}
    for record in _non_system_project_records(records):
        is_current = project_name is not None and record.project_name == project_name
        if not is_current or include_current_aliases:
            occupied.update(normalize_project_aliases(record.aliases))
        if not is_current or include_current_display_name:
            if record.display_name:
                occupied.add(record.display_name)
    return occupied


def allocate_project_name(
    desired_base_name: str,
    records: Sequence[ProjectRecordWire],
    *,
    project_name: str | None = None,
) -> str:
    """Return the first available logical project name for *desired_base_name*."""
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
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate

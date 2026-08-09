"""Locked mutations for project aliases and display names."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from sase.core.paths import is_valid_sase_project_name
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectRecordWire,
)
from sase.project_alias_records import (
    normalize_project_name,
    validate_project_aliases,
    validate_project_name,
)

ListProjectRecords = Callable[..., list[ProjectRecordWire]]
ResolveProjectRef = Callable[[str, Path | str | None], str]
ApplyAliasesUpdate = Callable[[str, Sequence[str]], str]
ApplyNameUpdate = Callable[[str, str | None], str]

_ALL_STATES = tuple(PROJECT_LIFECYCLE_STATES)


class ProjectAliasError(RuntimeError):
    """Base class for project alias service failures."""


class _ProjectAliasNotFoundError(ProjectAliasError):
    """Raised when a requested project cannot be resolved."""


def _get_project_record_from_records(
    records: Sequence[ProjectRecordWire],
    project: str,
) -> ProjectRecordWire:
    for record in records:
        if record.project_name == project:
            return record
    raise _ProjectAliasNotFoundError(f"project '{project}' was not found")


def _resolve_mutable_project_file(
    project: str,
    *,
    projects_root: Path,
    resolve_project_ref: ResolveProjectRef,
) -> tuple[str, Path]:
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    if project == "home":
        raise ProjectAliasError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise ProjectAliasError(f"invalid project name: {project!r}")

    project = resolve_project_ref(project, projects_root)
    project_dir = projects_root / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        raise _ProjectAliasNotFoundError(f"project '{project}' was not found")
    return project, project_file


def _reject_system_managed_record(record: ProjectRecordWire) -> None:
    if record.system_managed:
        raise ProjectAliasError(f"project '{record.project_name}' is system-managed")


def _validate_alias_arg(alias: str) -> None:
    if not is_valid_sase_project_name(alias):
        raise ProjectAliasError(f"invalid project alias: {alias!r}")


def _mutate_project_aliases_locked(
    project: str,
    update_aliases: Callable[[list[str]], list[str]],
    commit_msg: str,
    *,
    projects_root: Path,
    resolve_project_ref: ResolveProjectRef,
    list_project_records: ListProjectRecords,
    apply_project_aliases_update: ApplyAliasesUpdate,
) -> ProjectRecordWire:
    from sase.ace.patch import changespec_lock, write_changespec_atomic

    project, project_file = _resolve_mutable_project_file(
        project,
        projects_root=projects_root,
        resolve_project_ref=resolve_project_ref,
    )
    with changespec_lock(str(project_file)):
        records = list_project_records(
            projects_root,
            list(_ALL_STATES),
            include_home=True,
        )
        record = _get_project_record_from_records(records, project)
        _reject_system_managed_record(record)
        aliases = validate_project_aliases(
            record.project_name,
            update_aliases(list(record.aliases)),
            records,
        )
        content = project_file.read_text(encoding="utf-8")
        updated = apply_project_aliases_update(content, aliases)
        write_changespec_atomic(str(project_file), updated, commit_msg)

    return _get_project_record_from_records(
        list_project_records(projects_root, list(_ALL_STATES), include_home=True),
        project,
    )


def _mutate_project_name_locked(
    project: str,
    update_name: Callable[[str | None], str | None],
    commit_msg: str,
    *,
    projects_root: Path,
    resolve_project_ref: ResolveProjectRef,
    list_project_records: ListProjectRecords,
    apply_project_name_update: ApplyNameUpdate,
) -> ProjectRecordWire:
    from sase.ace.patch import changespec_lock, write_changespec_atomic

    project, project_file = _resolve_mutable_project_file(
        project,
        projects_root=projects_root,
        resolve_project_ref=resolve_project_ref,
    )
    with changespec_lock(str(project_file)):
        records = list_project_records(
            projects_root,
            list(_ALL_STATES),
            include_home=True,
        )
        record = _get_project_record_from_records(records, project)
        _reject_system_managed_record(record)
        name = validate_project_name(
            record.project_name,
            update_name(record.display_name),
            records,
        )
        content = project_file.read_text(encoding="utf-8")
        updated = apply_project_name_update(content, name)
        write_changespec_atomic(str(project_file), updated, commit_msg)

    return _get_project_record_from_records(
        list_project_records(projects_root, list(_ALL_STATES), include_home=True),
        project,
    )


def set_project_aliases_locked(
    project: str,
    aliases: list[str],
    *,
    projects_root: Path,
    resolve_project_ref: ResolveProjectRef,
    list_project_records: ListProjectRecords,
    apply_project_aliases_update: ApplyAliasesUpdate,
) -> ProjectRecordWire:
    """Replace aliases for *project* while holding the ProjectSpec lock."""
    return _mutate_project_aliases_locked(
        project,
        lambda _current: list(aliases),
        "Set project aliases",
        projects_root=projects_root,
        resolve_project_ref=resolve_project_ref,
        list_project_records=list_project_records,
        apply_project_aliases_update=apply_project_aliases_update,
    )


def add_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path,
    resolve_project_ref: ResolveProjectRef,
    list_project_records: ListProjectRecords,
    apply_project_aliases_update: ApplyAliasesUpdate,
) -> ProjectRecordWire:
    """Add *alias* to *project* while holding the ProjectSpec lock."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: [*aliases, alias],
        f"Add project alias {alias}",
        projects_root=projects_root,
        resolve_project_ref=resolve_project_ref,
        list_project_records=list_project_records,
        apply_project_aliases_update=apply_project_aliases_update,
    )


def remove_project_alias_locked(
    project: str,
    alias: str,
    *,
    projects_root: Path,
    resolve_project_ref: ResolveProjectRef,
    list_project_records: ListProjectRecords,
    apply_project_aliases_update: ApplyAliasesUpdate,
) -> ProjectRecordWire:
    """Remove *alias* from *project* while holding the ProjectSpec lock."""
    _validate_alias_arg(alias)
    return _mutate_project_aliases_locked(
        project,
        lambda aliases: [item for item in aliases if item != alias],
        f"Remove project alias {alias}",
        projects_root=projects_root,
        resolve_project_ref=resolve_project_ref,
        list_project_records=list_project_records,
        apply_project_aliases_update=apply_project_aliases_update,
    )


def set_project_name_locked(
    project: str,
    name: str | None,
    *,
    projects_root: Path,
    commit_msg: str,
    preserve_existing: bool,
    resolve_project_ref: ResolveProjectRef,
    list_project_records: ListProjectRecords,
    apply_project_name_update: ApplyNameUpdate,
) -> ProjectRecordWire:
    """Replace ``PROJECT_NAME`` while holding the ProjectSpec lock."""
    normalized = normalize_project_name(name)
    return _mutate_project_name_locked(
        project,
        lambda current: (
            current if preserve_existing and current == normalized else name
        ),
        commit_msg,
        projects_root=projects_root,
        resolve_project_ref=resolve_project_ref,
        list_project_records=list_project_records,
        apply_project_name_update=apply_project_name_update,
    )
